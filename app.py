#!/usr/bin/env python3
"""
app.py - Windows GUI for AI-Powered Video Fixer
Built with FreeSimpleGUI. Runs asynchronous background processing to ensure responsive UI.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import FreeSimpleGUI as sg

from src.ai_analyzer import query_gemini_diagnostics, validate_and_apply_ai_recommendation
from src.batch_processor import BatchProcessor, JobResult
from src.config import PROFILES, config
from src.logging_config import logger
from src.media_analyzer import analyze_media
from src.media_probe import VIDEO_EXTS, probe_media

APP_TITLE = "AI Video Fixer & Transcoder for Windows"
THEME = "DarkBlue3"


class VideoFixerGUI:
    def __init__(self):
        self.files: List[str] = []
        self.processor: Optional[BatchProcessor] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.is_processing = False

    def build_layout(self) -> List[List[sg.Element]]:
        sg.theme(THEME)

        # Status text for Gemini & FFmpeg
        env_status = "Configured" if config.has_gemini_key else "Missing / Not configured (Local fallback active)"
        bin_status = "Available" if config.ffmpeg_path and config.ffprobe_path else "Missing FFmpeg/FFprobe!"

        status_bar = [
            sg.Frame(
                "System & API Status",
                [
                    [
                        sg.Text(f"FFmpeg / FFprobe: {bin_status}", key="-STATUS-BIN-", text_color="#66BB6A" if "Available" in bin_status else "#EF5350"),
                        sg.Text("|"),
                        sg.Text(f"Gemini API: {env_status}", key="-STATUS-GEMINI-", text_color="#66BB6A" if "Configured" in env_status else "#FFA726"),
                        sg.Text(f"({config.gemini_model})", key="-STATUS-MODEL-", font=("Segoe UI", 8)),
                        sg.Push(),
                        sg.Button("Set API Key...", key="-SET-KEY-", size=(12, 1)),
                    ]
                ],
                expand_x=True,
                font=("Segoe UI", 9, "bold"),
            )
        ]

        # File Selection Frame
        input_frame = [
            sg.Frame(
                "Input Media",
                [
                    [
                        sg.Button("Add Files...", key="-ADD-FILES-", size=(12, 1)),
                        sg.Button("Add Folder...", key="-ADD-FOLDER-", size=(12, 1)),
                        sg.Button("Clear All", key="-CLEAR-", size=(10, 1)),
                        sg.Text("0 files loaded", key="-FILE-COUNT-", font=("Segoe UI", 9, "italic")),
                    ],
                    [
                        sg.Table(
                            values=[],
                            headings=["Filename", "Status", "Resolution", "V-Codec", "PixFmt", "Audio", "Duration", "Action"],
                            auto_size_columns=False,
                            col_widths=[26, 14, 11, 10, 11, 8, 9, 12],
                            justification="left",
                            num_rows=8,
                            key="-TABLE-",
                            enable_events=True,
                            expand_x=True,
                            expand_y=True,
                        )
                    ],
                ],
                expand_x=True,
                font=("Segoe UI", 9, "bold"),
            )
        ]

        # Settings Frame
        settings_frame = [
            sg.Frame(
                "Encoding & Profile Settings",
                [
                    [
                        sg.Text("Compatibility Profile:"),
                        sg.Combo(
                            list(PROFILES.keys()),
                            default_value="phone_compatible",
                            key="-PROFILE-",
                            readonly=True,
                            size=(20, 1),
                        ),
                        sg.Checkbox("Enable Gemini AI Analysis", default=config.ai_enabled and config.has_gemini_key, key="-USE-AI-"),
                        sg.Text("Mode:"),
                        sg.Combo(
                            ["Automatic (Inspect & Fix)", "Remux Only (+faststart)", "Transcode Only"],
                            default_value="Automatic (Inspect & Fix)",
                            key="-MODE-",
                            readonly=True,
                            size=(24, 1),
                        ),
                    ],
                    [
                        sg.Text("Output Directory:"),
                        sg.Input(key="-OUTDIR-", size=(45, 1)),
                        sg.FolderBrowse(target="-OUTDIR-"),
                        sg.Text("Suffix:"),
                        sg.Input("_fixed", key="-SUFFIX-", size=(8, 1)),
                        sg.Button("Open Output Folder", key="-OPEN-OUTDIR-"),
                    ],
                ],
                expand_x=True,
                font=("Segoe UI", 9, "bold"),
            )
        ]

        # Progress and Action Frame
        action_frame = [
            [
                sg.ProgressBar(max_value=100, orientation="h", size=(35, 18), key="-PROG-FILE-", expand_x=True),
                sg.Button("Inspect Files", key="-INSPECT-", size=(14, 1), button_color=("white", "#1E88E5")),
                sg.Button("Start Processing", key="-START-", size=(15, 1), button_color=("white", "#2E7D32")),
                sg.Button("Cancel", key="-CANCEL-", size=(10, 1), button_color=("white", "#C62828"), disabled=True),
            ],
            [
                sg.Text("Ready", key="-STATUS-TEXT-", expand_x=True, font=("Segoe UI", 9, "bold")),
            ],
        ]

        # Log Frame
        log_frame = [
            sg.Frame(
                "Activity Log & Diagnostic Details",
                [
                    [
                        sg.Multiline(
                            "",
                            key="-LOG-",
                            size=(90, 8),
                            autoscroll=True,
                            expand_x=True,
                            expand_y=True,
                            font=("Consolas", 9),
                            background_color="#181818",
                            text_color="#E0E0E0",
                        )
                    ]
                ],
                expand_x=True,
                expand_y=True,
                font=("Segoe UI", 9, "bold"),
            )
        ]

        return [
            status_bar,
            input_frame,
            settings_frame,
            action_frame,
            log_frame,
        ]

    def log(self, window: sg.Window, message: str):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        window["-LOG-"].update(line, append=True)

    def add_files(self, new_paths: List[str], window: sg.Window):
        added = 0
        for p in new_paths:
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXTS:
                if p not in self.files:
                    self.files.append(p)
                    added += 1
            elif os.path.isdir(p):
                for root, _, filenames in os.walk(p):
                    for name in sorted(filenames):
                        if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                            full_path = os.path.join(root, name)
                            if full_path not in self.files:
                                self.files.append(full_path)
                                added += 1

        window["-FILE-COUNT-"].update(f"{len(self.files)} file(s) loaded")
        self.log(window, f"Added {added} video file(s). Total: {len(self.files)}")
        self.refresh_table(window)

    def refresh_table(self, window: sg.Window, table_data: Optional[List[List[str]]] = None):
        if table_data is not None:
            window["-TABLE-"].update(values=table_data)
            return

        rows = []
        for f in self.files:
            rows.append([os.path.basename(f), "Pending", "-", "-", "-", "-", "-", "Pending"])
        window["-TABLE-"].update(values=rows)

    def run_inspection(self, window: sg.Window):
        """Inspects all loaded files deterministically and optionally with Gemini."""
        if not self.files:
            self.log(window, "No files to inspect.")
            return

        profile_key = window["-PROFILE-"].get()
        target_profile = PROFILES.get(profile_key, PROFILES["phone_compatible"])
        use_ai = window["-USE-AI-"].get()

        self.log(window, f"Starting inspection of {len(self.files)} files (Profile: {target_profile.name})...")
        rows = []

        for i, path in enumerate(self.files):
            try:
                meta = probe_media(path)
                analysis = analyze_media(meta, profile=target_profile)

                if use_ai:
                    ai_rec, ai_err = query_gemini_diagnostics(meta, analysis)
                    if ai_rec:
                        analysis = validate_and_apply_ai_recommendation(ai_rec, analysis)

                v = meta.video_streams[0] if meta.video_streams else None
                res_str = f"{v.width}x{v.height}" if v else "-"
                vcodec = v.codec_name if v else "-"
                pix_fmt = v.pix_fmt if v else "-"
                audio_str = f"{len(meta.audio_streams)} trk" if meta.audio_streams else "None"
                dur_str = f"{meta.duration:.1f}s"

                rows.append([
                    os.path.basename(path),
                    analysis.status.upper(),
                    res_str,
                    vcodec,
                    pix_fmt,
                    audio_str,
                    dur_str,
                    analysis.action.upper(),
                ])
                self.log(window, f"[{analysis.status.upper()}] {os.path.basename(path)}: {analysis.summary()}")
            except Exception as e:
                rows.append([os.path.basename(path), "ERROR", "-", "-", "-", "-", "-", "ERROR"])
                self.log(window, f"[ERROR] Failed to inspect {os.path.basename(path)}: {e}")

        self.refresh_table(window, table_data=rows)
        window["-STATUS-TEXT-"].update("Inspection complete.")

    def start_batch_processing(self, window: sg.Window, values: Dict):
        """Launches batch processing in a background worker thread."""
        if not self.files:
            sg.popup_ok("Please add at least one video file before starting.", title="No Files")
            return

        profile_key = values["-PROFILE-"]
        target_profile = PROFILES.get(profile_key, PROFILES["phone_compatible"])
        out_dir = values["-OUTDIR-"].strip() or None
        suffix = values["-SUFFIX-"].strip() or "_fixed"
        use_ai = values["-USE-AI-"]
        mode_val = values["-MODE-"]

        force_mode = None
        if "Remux Only" in mode_val:
            force_mode = "remux_only"
        elif "Transcode Only" in mode_val:
            force_mode = "transcode_only"

        self.processor = BatchProcessor(
            profile=target_profile,
            out_dir=out_dir,
            suffix=suffix,
            use_ai=use_ai,
            force_mode=force_mode,
        )

        self.is_processing = True
        window["-START-"].update(disabled=True)
        window["-INSPECT-"].update(disabled=True)
        window["-CANCEL-"].update(disabled=False)

        def worker():
            total = len(self.files)
            for idx, src_path in enumerate(self.files):
                if self.processor.is_cancelled():
                    break

                window.write_event_value("-JOB-FILE-START-", (idx, src_path))

                def progress_cb(frac: float):
                    window.write_event_value("-JOB-PROG-", (idx, frac))

                result = self.processor.process_file(src_path, on_progress=progress_cb)
                window.write_event_value("-JOB-FILE-DONE-", (idx, result))

            window.write_event_value("-JOB-BATCH-COMPLETE-", None)

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def main_loop(self):
        window = sg.Window(
            APP_TITLE,
            self.build_layout(),
            resizable=True,
            finalize=True,
            size=(960, 640),
            icon=None,
        )

        while True:
            event, values = window.read(timeout=100)

            if event in (sg.WIN_CLOSED, "Exit"):
                if self.processor:
                    self.processor.cancel()
                break

            elif event == "-SET-KEY-":
                key_input = sg.popup_get_text(
                    "Enter your Google Gemini API Key:\n(Will be saved locally to .env next to the application)",
                    title="Configure Gemini API Key",
                    default_text=config.gemini_api_key if config.has_gemini_key else "",
                    password_char="*",
                )
                if key_input is not None and key_input.strip():
                    config.save_api_key(key_input.strip())
                    window["-STATUS-GEMINI-"].update("Gemini API: Configured", text_color="#66BB6A")
                    window["-USE-AI-"].update(value=True)
                    self.log(window, "Gemini API key successfully saved to .env!")

            elif event == "-ADD-FILES-":
                picked = sg.popup_get_file(
                    "Select Video File(s)",
                    multiple_files=True,
                    file_types=(("Video Files", "*.mp4;*.m4v;*.mov;*.mkv;*.avi;*.ts;*.webm"), ("All Files", "*.*")),
                )
                if picked:
                    paths = [p.strip() for p in picked.split(";") if p.strip()]
                    self.add_files(paths, window)

            elif event == "-ADD-FOLDER-":
                folder = sg.popup_get_folder("Select Folder with Videos")
                if folder:
                    self.add_files([folder], window)

            elif event == "-CLEAR-":
                self.files.clear()
                window["-FILE-COUNT-"].update("0 files loaded")
                self.refresh_table(window)
                self.log(window, "Cleared file list.")

            elif event == "-INSPECT-":
                threading.Thread(target=self.run_inspection, args=(window,), daemon=True).start()

            elif event == "-START-":
                self.start_batch_processing(window, values)

            elif event == "-CANCEL-":
                if self.processor:
                    self.processor.cancel()
                    self.log(window, "Cancellation requested by user. Waiting for active operations to terminate...")
                    window["-CANCEL-"].update(disabled=True)

            elif event == "-OPEN-OUTDIR-":
                out_dir = values["-OUTDIR-"].strip()
                target_dir = out_dir if out_dir and os.path.isdir(out_dir) else os.getcwd()
                if sys.platform == "win32":
                    os.startfile(target_dir)
                else:
                    subprocess.run(["xdg-open", target_dir])

            # Background thread events
            elif event == "-JOB-FILE-START-":
                idx, src_path = values[event]
                window["-STATUS-TEXT-"].update(f"Processing ({idx + 1}/{len(self.files)}): {os.path.basename(src_path)}")
                self.log(window, f"Processing file {idx + 1}/{len(self.files)}: {os.path.basename(src_path)}")
                window["-PROG-FILE-"].update(current_count=0)

            elif event == "-JOB-PROG-":
                idx, frac = values[event]
                pct = int(frac * 100)
                window["-PROG-FILE-"].update(current_count=pct)

            elif event == "-JOB-FILE-DONE-":
                idx, job = values[event]
                window["-PROG-FILE-"].update(current_count=100)
                status_disp = job.status.upper()
                if job.status == "completed":
                    self.log(window, f"[DONE] {os.path.basename(job.source_path)} -> {job.action_taken.upper()} verified.")
                else:
                    self.log(window, f"[{status_disp}] {os.path.basename(job.source_path)}: {job.error_message}")

            elif event == "-JOB-BATCH-COMPLETE-":
                self.is_processing = False
                window["-START-"].update(disabled=False)
                window["-INSPECT-"].update(disabled=False)
                window["-CANCEL-"].update(disabled=True)
                window["-STATUS-TEXT-"].update("Batch processing finished.")
                self.log(window, "=== Batch processing complete ===")
                sg.popup_ok("Batch processing has finished!", title="Completed")

        window.close()


def main():
    gui = VideoFixerGUI()
    gui.main_loop()


if __name__ == "__main__":
    main()
