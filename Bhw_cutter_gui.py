#!/usr/bin/env python3
"""
Bhw Cutter GUI - By Baraa Hawamdeh
Standalone single-file GUI wrapper that performs scene removal/cutting
without using movies.json. Drop this next to your video files
or use it standalone (it includes the necessary cutting logic).

Prereqs:
    pip install FreeSimpleGUI
    ffmpeg and ffprobe available in PATH (or next to script, or set FFMPEG/FFPROBE)

Build to EXE (optional):
    pip install pyinstaller
    pyinstaller --noconsole --onefile Bhw_cutter_gui.py
"""

import os
import re
import subprocess
import sys
import tempfile
import time
import shutil
import threading
from pathlib import Path
from typing import List, Tuple, Optional

import FreeSimpleGUI as sg

# ---------------- Locate Binaries ----------------

def resolve_binary(binary_name: str, env_var: str) -> Optional[str]:
    """
    Search for executable in:
    1. Environment variable if set and exists.
    2. Next to the script or EXE (current directory & executable directory).
    3. System PATH via shutil.which.
    """
    env_val = os.environ.get(env_var, "").strip()
    if env_val and os.path.isfile(env_val):
        return env_val

    # Directory where script or frozen exe is located
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # Check next to script/exe
    candidate = os.path.join(base_dir, f"{binary_name}.exe" if sys.platform == "win32" else binary_name)
    if os.path.isfile(candidate):
        return candidate

    # Check current working directory
    cwd_candidate = os.path.join(os.getcwd(), f"{binary_name}.exe" if sys.platform == "win32" else binary_name)
    if os.path.isfile(cwd_candidate):
        return cwd_candidate

    # Check PATH
    found = shutil.which(binary_name)
    if found:
        return found

    return None

FFMPEG = resolve_binary("ffmpeg", "FFMPEG")
FFPROBE = resolve_binary("ffprobe", "FFPROBE")

# ---------------- Configuration ----------------
TEMP_ROOT = os.path.join(tempfile.gettempdir(), "bhw_cutter_parts")
GPU_ENCODER = "h264_nvenc"
NVENC_RATECTRL = ["-rc", "vbr_hq", "-cq", "19"]
NVENC_PRESET = ["-preset", "p2"]
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"

# UI strings
AUTHOR = "By Baraa Hawamdeh"
APP_TITLE = f"Bhw Cutter GUI — {AUTHOR}"

# Global process tracking and cancel flag
current_process: Optional[subprocess.Popen] = None
process_lock = threading.Lock()
cancel_requested = False

# ---------------- Utilities ----------------

def ensure_temp_dir():
    os.makedirs(TEMP_ROOT, exist_ok=True)


def run_subprocess_live(cmd: List[str], window: sg.Window, out_key: str = "-LOG-") -> int:
    """Run command, register it globally for cancellation, and stream output via events."""
    global current_process, cancel_requested
    if cancel_requested:
        return 1

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        with process_lock:
            current_process = proc
    except Exception as e:
        window.write_event_value("-LOG_LINE-", f"Failed to start: {e}")
        return 1

    # Read stdout and stderr
    def stream_reader(pipe):
        try:
            for line in iter(pipe.readline, ''):
                if line:
                    window.write_event_value("-LOG_LINE-", line.rstrip())
            pipe.close()
        except Exception:
            pass

    t_out = threading.Thread(target=stream_reader, args=(proc.stdout,), daemon=True)
    t_err = threading.Thread(target=stream_reader, args=(proc.stderr,), daemon=True)
    t_out.start()
    t_err.start()

    proc.wait()
    t_out.join()
    t_err.join()

    with process_lock:
        current_process = None

    if cancel_requested:
        window.write_event_value("-LOG_LINE-", "[INFO] Process stopped by user.")
        return 1

    return proc.returncode if proc.returncode is not None else 1


def ffprobe_duration(path: str, window: Optional[sg.Window] = None) -> float:
    """Run ffprobe to get video duration, logging clear details on failure."""
    if not FFPROBE:
        msg = "[ERROR] ffprobe is not found in PATH or script directory."
        if window:
            window.write_event_value("-LOG_LINE-", msg)
        else:
            print(msg)
        return 0.0

    try:
        res = subprocess.run([
            FFPROBE,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ], capture_output=True, text=True)

        if res.returncode != 0:
            err_msg = f"[WARN] ffprobe failed (code {res.returncode}): {res.stderr.strip()}"
            if window:
                window.write_event_value("-LOG_LINE-", err_msg)
            else:
                print(err_msg)
            return 0.0

        dur_str = res.stdout.strip()
        if not dur_str:
            err_msg = "[WARN] ffprobe returned empty duration output."
            if window:
                window.write_event_value("-LOG_LINE-", err_msg)
            return 0.0

        return float(dur_str)
    except Exception as e:
        err_msg = f"[WARN] ffprobe exception for '{path}': {e}"
        if window:
            window.write_event_value("-LOG_LINE-", err_msg)
        else:
            print(err_msg)
        return 0.0


def parse_time_to_seconds(t: str) -> float:
    """Support formats: SS, M:SS, H:MM:SS (also allow leading/trailing spaces)."""
    t = t.strip()
    if not t:
        return 0.0
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    parts = t.split(":")
    try:
        parts = [float(p) for p in parts]
    except Exception:
        return 0.0
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        m, s = parts
        return m * 60.0 + s
    h = parts[-3]
    m = parts[-2]
    s = parts[-1]
    return h * 3600.0 + m * 60.0 + s


# ---------------- Parsing user textbox ----------------

EPISODE_HEADER_RE = re.compile(r"^\s*(?:E|EP|EPISODE)?\s*([0-9A-Za-z_\-\.]+)\s*$", re.IGNORECASE)
TIME_RANGE_RE = re.compile(r"^(?P<a>[^\-\s]+)\s*[-–—]\s*(?P<b>[^\s]+)\s*$")


def parse_episodes_text(text: str) -> dict:
    lines = text.splitlines()
    episodes = {}
    current = None
    for raw in lines:
        line = raw.strip()
        if not line:
            current = None
            continue
        m_hdr = EPISODE_HEADER_RE.match(line)
        m_time = TIME_RANGE_RE.match(line)
        if m_hdr and not m_time:
            name = m_hdr.group(1)
            safe = re.sub(r"[^0-9A-Za-z_\-\. ]+", "", name).strip()
            safe = safe.replace(" ", "_")
            current = safe
            if current not in episodes:
                episodes[current] = []
            continue
        if line.lower() == "clear" and current:
            episodes[current] = []
            continue
        if current and m_time:
            a = m_time.group("a")
            b = m_time.group("b")
            sa = parse_time_to_seconds(a)
            sb = parse_time_to_seconds(b)
            if sb <= sa:
                continue
            episodes[current].append((round(sa, 3), round(sb, 3)))
            continue
        if current is None:
            name = line
            safe = re.sub(r"[^0-9A-Za-z_\-\. ]+", "", name).strip().replace(" ", "_")
            current = safe
            episodes[current] = []
            continue
    return episodes


# ---------------- FFmpeg cutting strategies ----------------

def safe_path_for_concat(p: str) -> str:
    p_forward = p.replace("\\", "/")
    return p_forward.replace("'", "'\\''")


def concat_demuxer(parts: List[str], out_path: str, window: sg.Window) -> bool:
    global cancel_requested
    if not parts or cancel_requested:
        return False
    concat_txt = os.path.join(TEMP_ROOT, f"segments_{int(time.time())}.txt")
    try:
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{safe_path_for_concat(p)}'\n")
        cmd = [
            FFMPEG,
            "-y",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_txt,
            "-c",
            "copy",
            out_path,
        ]
        window.write_event_value("-LOG_LINE-", "Running concat demuxer (stream-copy)...")
        rc = run_subprocess_live(cmd, window)
        if rc == 0 and os.path.exists(out_path):
            return True
        if cancel_requested:
            return False

        window.write_event_value("-LOG_LINE-", "Concat demuxer failed, trying re-encode concat (NVENC)...")
        cmd_nvenc = [
            FFMPEG,
            "-y",
            "-nostdin",
            "-hwaccel",
            "cuda",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_txt,
        ] + NVENC_PRESET + NVENC_RATECTRL + [
            "-c:v",
            GPU_ENCODER,
            "-c:a",
            AUDIO_CODEC,
            "-ac",
            "2",
            "-b:a",
            AUDIO_BITRATE,
            out_path,
        ]
        rc2 = run_subprocess_live(cmd_nvenc, window)
        if rc2 == 0 and os.path.exists(out_path):
            return True
        if cancel_requested:
            return False

        # CPU fallback
        cmd_cpu = [
            FFMPEG,
            "-y",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_txt,
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-c:a",
            AUDIO_CODEC,
            "-ac",
            "2",
            "-b:a",
            AUDIO_BITRATE,
            out_path,
        ]
        rc3 = run_subprocess_live(cmd_cpu, window)
        return rc3 == 0 and os.path.exists(out_path)
    finally:
        try:
            if os.path.exists(concat_txt):
                os.remove(concat_txt)
        except Exception:
            pass


def try_streamcopy_segment(input_path: str, start: float, end: float, out_path: str, window: sg.Window) -> bool:
    if cancel_requested:
        return False
    cmd = [
        FFMPEG,
        "-y",
        "-nostdin",
        "-ss",
        str(start),
        "-to",
        str(end),
        "-i",
        input_path,
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-fflags",
        "+genpts",
        out_path,
    ]
    rc = run_subprocess_live(cmd, window)
    return rc == 0 and os.path.exists(out_path)


def try_reencode_segment_nvenc(input_path: str, start: float, end: float, out_path: str, window: sg.Window, force_cpu=False) -> bool:
    if cancel_requested:
        return False
    if not force_cpu:
        cmd = [
            FFMPEG,
            "-y",
            "-nostdin",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            input_path,
        ] + NVENC_PRESET + NVENC_RATECTRL + [
            "-c:v",
            GPU_ENCODER,
            "-c:a",
            AUDIO_CODEC,
            "-ac",
            "2",
            "-b:a",
            AUDIO_BITRATE,
            "-avoid_negative_ts",
            "make_zero",
            out_path,
        ]
        rc = run_subprocess_live(cmd, window)
        if rc == 0 and os.path.exists(out_path):
            return True
        if cancel_requested:
            return False

    # CPU fallback
    cmd_cpu = [
        FFMPEG,
        "-y",
        "-nostdin",
        "-ss",
        str(start),
        "-to",
        str(end),
        "-i",
        input_path,
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-c:a",
        AUDIO_CODEC,
        "-ac",
        "2",
        "-b:a",
        AUDIO_BITRATE,
        "-avoid_negative_ts",
        "make_zero",
        out_path,
    ]
    rc2 = run_subprocess_live(cmd_cpu, window)
    return rc2 == 0 and os.path.exists(out_path)


def create_segment_flexible(input_path: str, start: float, end: float, idx: int, window: sg.Window) -> str:
    if cancel_requested:
        return ""
    ensure_temp_dir()
    out_file = os.path.join(TEMP_ROOT, f"part_{int(time.time())}_{idx}.mp4")
    if try_streamcopy_segment(input_path, start, end, out_file, window):
        return out_file
    if try_reencode_segment_nvenc(input_path, start, end, out_file, window, force_cpu=False):
        return out_file
    if try_reencode_segment_nvenc(input_path, start, end, out_file, window, force_cpu=True):
        return out_file
    return ""


def filter_complex_concat(input_path: str, segments: List[Tuple[float, float]], out_path: str, window: sg.Window) -> bool:
    if not segments or cancel_requested:
        return False
    vf_parts = []
    af_parts = []
    for i, (s, e) in enumerate(segments):
        vf_parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        af_parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
    concat_inputs = "".join([f"[v{i}][a{i}]" for i in range(len(segments))])
    filter_complex = ";".join(vf_parts + af_parts + [f"{concat_inputs}concat=n={len(segments)}:v=1:a=1[outv][outa]"])
    cmd = [
        FFMPEG,
        "-y",
        "-nostdin",
        "-i",
        input_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
    ] + NVENC_PRESET + NVENC_RATECTRL + [
        "-c:v",
        GPU_ENCODER,
        "-c:a",
        AUDIO_CODEC,
        "-ac",
        "2",
        "-b:a",
        AUDIO_BITRATE,
        out_path,
    ]
    window.write_event_value("-LOG_LINE-", "Trying filter_complex (single-call concat)...")
    rc = run_subprocess_live(cmd, window)
    if rc == 0 and os.path.exists(out_path):
        return True
    if cancel_requested:
        return False

    window.write_event_value("-LOG_LINE-", "filter_complex NVENC failed, trying CPU fallback...")
    cmd_cpu = [
        FFMPEG,
        "-y",
        "-nostdin",
        "-i",
        input_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-c:a",
        AUDIO_CODEC,
        "-ac",
        "2",
        "-b:a",
        AUDIO_BITRATE,
        out_path,
    ]
    rc2 = run_subprocess_live(cmd_cpu, window)
    return rc2 == 0 and os.path.exists(out_path)


def build_keep_segments(unwanted: List[Tuple[float, float]], duration: float) -> List[Tuple[float, float]]:
    if not unwanted:
        return [(0.0, duration)]
    intervals = sorted([(max(0.0, float(s)), min(float(e), duration)) for s, e in unwanted], key=lambda x: x[0])
    keep = []
    last = 0.0
    for s, e in intervals:
        if s > last:
            keep.append((last, s))
        last = max(last, e)
    if last < duration:
        keep.append((last, duration))
    keep = [(round(a, 3), round(b, 3)) for a, b in keep if (b - a) > 0.05]
    return keep


# ---------------- High-level processing per episode ----------------

def process_episode(input_folder: str, output_folder: str, ep_name: str, unwanted: List[Tuple[float, float]], window: sg.Window) -> Tuple[str, str]:
    global cancel_requested
    if cancel_requested:
        return ep_name, "Cancelled"

    candidates = []
    for ext in (".mp4", ".mkv", ".mov", ".ts", ".m4v"):
        candidates.append(os.path.join(input_folder, ep_name + ext))

    found = ""
    for root, dirs, files in os.walk(input_folder):
        for f in files:
            name_no_ext = os.path.splitext(f)[0]
            if name_no_ext.lower() == ep_name.lower():
                found = os.path.join(root, f)
                break
        if found:
            break

    if not found:
        for c in candidates:
            if os.path.exists(c):
                found = c
                break

    basename = ep_name
    if not found or not os.path.exists(found):
        window.write_event_value("-LOG_LINE-", f"[WARN] Input file not found for {ep_name} (tried {len(candidates)} candidates). Skipping.")
        return basename, "Missing-Input"

    duration = ffprobe_duration(found, window)
    if duration <= 0:
        window.write_event_value("-LOG_LINE-", f"[WARN] Could not determine duration for {basename}. Copying original to output.")
        out_path = os.path.join(output_folder, os.path.basename(found))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cmd = [FFMPEG, "-y", "-nostdin", "-i", found, "-c", "copy", out_path]
        rc = run_subprocess_live(cmd, window)
        return basename, "Copied-NoDuration" if rc == 0 else "CopyFailed"

    if cancel_requested:
        return basename, "Cancelled"

    keep = build_keep_segments(unwanted, duration)
    if not keep:
        out_path = os.path.join(output_folder, os.path.basename(found))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        window.write_event_value("-LOG_LINE-", f"No keep segments after removing unwanted for {basename}. Copying original.")
        cmd = [FFMPEG, "-y", "-nostdin", "-i", found, "-c", "copy", out_path]
        rc = run_subprocess_live(cmd, window)
        return basename, "Copied-NoKeep" if rc == 0 else "CopyFailed"

    out_path = os.path.join(output_folder, f"{ep_name}.mp4")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if len(keep) == 1 and abs(keep[0][0] - 0.0) < 1e-3 and abs(keep[0][1] - duration) < 1e-3:
        window.write_event_value("-LOG_LINE-", f"Keep covers full file for {basename}, copying original.")
        cmd = [FFMPEG, "-y", "-nostdin", "-i", found, "-c", "copy", out_path]
        rc = run_subprocess_live(cmd, window)
        return basename, "Copied-NoCuts" if rc == 0 else "CopyFailed"

    # Strategy 1
    if filter_complex_concat(found, keep, out_path, window):
        return basename, "Success-FilterComplex"
    if cancel_requested:
        return basename, "Cancelled"

    # Strategy 2
    window.write_event_value("-LOG_LINE-", f"Filter_complex failed for {basename}, creating parts and trying concat demuxer...")
    ensure_temp_dir()
    parts = []
    for idx, (s, e) in enumerate(keep):
        if cancel_requested:
            break
        part = create_segment_flexible(found, s, e, idx, window)
        if part:
            parts.append(part)
        else:
            window.write_event_value("-LOG_LINE-", f"Failed to create part {idx} for {basename} ({s}-{e}).")

    if parts and not cancel_requested:
        ok = concat_demuxer(parts, out_path, window)
        for p in parts:
            try:
                os.remove(p)
            except Exception:
                pass
        if ok and os.path.exists(out_path):
            return basename, "Success-Demuxer"

    if cancel_requested:
        return basename, "Cancelled"

    # Strategy 3
    window.write_event_value("-LOG_LINE-", f"Last resort: re-encoding parts with CPU for {basename}...")
    re_parts = []
    for idx, (s, e) in enumerate(keep):
        if cancel_requested:
            break
        out_part = os.path.join(TEMP_ROOT, f"reenc_{int(time.time())}_{idx}.mp4")
        if try_reencode_segment_nvenc(found, s, e, out_part, window, force_cpu=True):
            re_parts.append(out_part)

    if re_parts and not cancel_requested:
        ok2 = concat_demuxer(re_parts, out_path, window)
        for p in re_parts:
            try:
                os.remove(p)
            except Exception:
                pass
        if ok2 and os.path.exists(out_path):
            return basename, "Success-ReencodedParts"

    if cancel_requested:
        return basename, "Cancelled"

    # Fallback copy
    window.write_event_value("-LOG_LINE-", f"All strategies failed for {basename}. Copying original as fallback.")
    cmd = [FFMPEG, "-y", "-nostdin", "-i", found, "-c", "copy", out_path]
    rc = run_subprocess_live(cmd, window)
    return basename, "Fallback-Copy" if rc == 0 else "Failed"


# ---------------- Worker Thread ----------------

def processing_worker(in_folder: str, out_folder: str, episodes: dict, window: sg.Window):
    global cancel_requested
    cancel_requested = False
    window.write_event_value("-LOG_LINE-", f"Starting run — found {len(episodes)} episode(s)")

    for ep, ranges in episodes.items():
        if cancel_requested:
            window.write_event_value("-LOG_LINE-", "[INFO] Job was cancelled by user.")
            break
        window.write_event_value("-LOG_LINE-", f"\n=== Processing: {ep} ===")
        basename, status = process_episode(in_folder, out_folder, ep, ranges, window)
        window.write_event_value("-LOG_LINE-", f"Result: {basename} -> {status}\n")

    if not cancel_requested:
        window.write_event_value("-LOG_LINE-", "\nAll done.\n")
    window.write_event_value("-PROCESSING_DONE-", None)


# ---------------- GUI Layout ----------------

layout = [
    [sg.Text(APP_TITLE, font=("Any", 16), justification="center")],
    [sg.Text(AUTHOR, font=("Any", 10), pad=((0, 0), (0, 10)))],
    [sg.Text("Input Folder:"), sg.InputText(key="-IN-", expand_x=True), sg.FolderBrowse(button_text="Browse")],
    [sg.Text("Output Folder:"), sg.InputText(key="-OUT-", expand_x=True), sg.FolderBrowse(button_text="Browse")],
    [sg.Text("Paste episode blocks below (example format shown on right):")],
    [
        sg.Multiline(default_text="E01\n29:32-30:17\n44:22-45:15\n\nE02\nclear\n\nE03\n17:33-17:42",
                     size=(60, 12), key="-TEXT-", expand_x=True, expand_y=True),
        sg.Column([
            [sg.Text("Example format:")],
            [sg.Text("E01\n29:32-30:17\n44:22-45:15\n\nE02\nclear", size=(30,6))],
            [sg.Text("Tips:" )],
            [sg.Text("- Use HH:MM:SS or MM:SS or seconds")],
            [sg.Text("- 'clear' under an episode => no cuts (copy)")]
        ], vertical_alignment="top")
    ],
    [sg.Button("Run Cutter", key="-RUN-", size=(12,1)), sg.Button("Stop", key="-STOP-", disabled=True), sg.Button("Clear Log", key="-CLR-")],
    [sg.Text("Live Log:" )],
    [sg.Multiline(size=(100, 20), key="-LOG-", autoscroll=True, disabled=True, expand_x=True, expand_y=True)],
    [sg.Text("Status:"), sg.Text("Idle", key="-STATUS-")],
]

window = sg.Window(APP_TITLE, layout, resizable=True, finalize=True)

# ---------------- Initial Startup Checks ----------------
missing_tools = []
if not FFMPEG:
    missing_tools.append("ffmpeg.exe")
if not FFPROBE:
    missing_tools.append("ffprobe.exe")

if missing_tools:
    missing_str = ", ".join(missing_tools)
    err_popup = (
        f"Missing required component(s): {missing_str}\n\n"
        "Please ensure FFmpeg and FFprobe are either:\n"
        "1. Added to your system/user PATH.\n"
        "2. Placed in the same directory as this script/EXE.\n"
        "3. Defined in environment variables FFMPEG and FFPROBE."
    )
    sg.popup_error(err_popup, title="FFmpeg Not Found")
    window["-LOG-"].print(f"[ERROR] {err_popup}")
else:
    window["-LOG-"].print(f"[INIT] ffmpeg path: {FFMPEG}")
    window["-LOG-"].print(f"[INIT] ffprobe path: {FFPROBE}")

# ---------------- Main Event Loop ----------------

worker_thread: Optional[threading.Thread] = None

while True:
    event, values = window.read(timeout=100)
    if event == sg.WIN_CLOSED:
        cancel_requested = True
        with process_lock:
            if current_process and current_process.poll() is None:
                try:
                    current_process.kill()
                except Exception:
                    pass
        break

    if event == "-CLR-":
        window["-LOG-"].update("")

    if event == "-LOG_LINE-":
        line = values.get("-LOG_LINE-")
        if line is not None:
            window["-LOG-"].print(line)

    if event == "-PROCESSING_DONE-":
        window["-RUN-"].update(disabled=False)
        window["-STOP-"].update(disabled=True)
        window["-STATUS-"].update("Idle" if not cancel_requested else "Stopped")

    if event == "-STOP-":
        cancel_requested = True
        with process_lock:
            if current_process and current_process.poll() is None:
                try:
                    current_process.kill()
                    window["-LOG-"].print("[STOP] Subprocess killed by user.")
                except Exception as ex:
                    window["-LOG-"].print(f"[STOP] Error killing process: {ex}")
        window["-STOP-"].update(disabled=True)
        window["-STATUS-"].update("Stopping...")

    if event == "-RUN-":
        if not FFMPEG or not FFPROBE:
            sg.popup_error("Cannot start: ffmpeg or ffprobe is missing!", title="Error")
            continue

        in_folder = values.get("-IN-", "")
        out_folder = values.get("-OUT-", "")
        text = values.get("-TEXT-", "")
        if not in_folder or not out_folder:
            sg.popup("Please select both input and output folders.")
            continue
        episodes = parse_episodes_text(text)
        if not episodes:
            sg.popup("No episodes parsed from textbox. Check format.")
            continue

        # UI updates
        window["-RUN-"].update(disabled=True)
        window["-STOP-"].update(disabled=False)
        window["-STATUS-"].update("Running")

        # Launch processing thread
        worker_thread = threading.Thread(
            target=processing_worker,
            args=(in_folder, out_folder, episodes, window),
            daemon=True
        )
        worker_thread.start()

window.close()
