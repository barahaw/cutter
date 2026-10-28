#!/usr/bin/env python3
"""
fixer.py - AI-assisted video inspection, repair, and encoding for Windows.

CLI:
    python fixer.py E04.mp4 E18.mp4
    python fixer.py "C:\\Videos" --outdir "C:\\Videos\\fixed" --suffix _fixed
    python fixer.py E04.mp4 --check-only
    python fixer.py E04.mp4 --profile phone_compatible --ai

From SceneTrim or other scripts:
    from fixer import fix_faststart, check_file, probe, has_faststart
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.ai_analyzer import query_gemini_diagnostics, validate_and_apply_ai_recommendation
from src.config import PROFILES, EncodingProfile, config, resolve_binary
from src.logging_config import logger
from src.media_analyzer import ClassificationResult, analyze_media
from src.media_probe import (
    MediaMetadata,
    has_faststart,
    probe_media,
    top_level_atoms,
)
from src.processing import remux_file, transcode_file
from src.verification import verify_output

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".ts", ".webm"}

# Maintain binary variables for backward compatibility
FFMPEG = config.ffmpeg_path
FFPROBE = config.ffprobe_path


def find_binary(name: str) -> Optional[str]:
    """Find binary executable for backward compatibility."""
    return resolve_binary(name, name.upper())


def probe(path: str) -> Dict:
    """Return dictionary with duration, video info, audio presence and extra stream count.
    Preserves exact backward-compatible dictionary structure for external callers.
    """
    meta = probe_media(path, ffprobe_bin=FFPROBE)
    if meta.probe_error:
        raise RuntimeError(meta.probe_error)

    return {
        "duration": meta.duration,
        "vcodec": meta.vcodec,
        "profile": meta.profile,
        "pix_fmt": meta.pix_fmt,
        "has_audio": meta.has_audio,
        "extra_streams": meta.extra_streams,
    }


def phone_compatible(info: Dict) -> bool:
    """Backward compatible check for standard H.264 mobile compatibility."""
    return (
        info.get("vcodec") == "h264"
        and info.get("pix_fmt") == "yuv420p"
        and (info.get("profile") or "").split()[0]
        in ("Baseline", "Constrained", "Main", "High")
    )


def check_file(path: str) -> Dict:
    """Status assessment for GUI lists and quick CLI checks.
    Preserves legacy status strings ('ok', 'needs-reencode', 'needs-fix', 'unknown')
    while populating full metadata.
    """
    meta = probe_media(path, ffprobe_bin=FFPROBE)
    fast = meta.has_faststart

    analysis = analyze_media(meta, profile=PROFILES["phone_compatible"])
    # Map modern classification to legacy status codes if needed
    if meta.probe_error:
        status = "unknown"
    elif analysis.status == "needs-transcode":
        status = "needs-reencode"
    elif analysis.status == "needs-remux":
        status = "needs-fix"
    elif analysis.status == "ok":
        status = "ok"
    else:
        status = "unknown"

    info = meta.to_dict()
    return {
        "status": status,
        "faststart": fast,
        "detailed_status": analysis.status,
        "reasons": analysis.reasons,
        "action": analysis.action,
        **info,
    }


def verify(src: str, out: str, tolerance: float = 1.0) -> bool:
    """Verify that moov is first and duration matches within tolerance."""
    src_meta = probe_media(src, ffprobe_bin=FFPROBE)
    res = verify_output(
        src_meta=src_meta,
        out_path=out,
        profile=PROFILES["phone_compatible"],
        tolerance=tolerance,
        run_decode=True,
    )
    return res.is_valid


def fix_faststart(
    src: str,
    dst: str,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Callable[[], bool] = lambda: False,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> bool:
    """Remux src -> dst with +faststart.
    Writes to a temporary file first and atomically renames only on verified success.
    """
    # Sync binaries in case external caller modified module attributes
    config.ffmpeg_path = FFMPEG
    config.ffprobe_path = FFPROBE

    try:
        meta = probe_media(src, ffprobe_bin=FFPROBE)
        tmp = remux_file(
            src=src,
            dst=dst,
            meta=meta,
            on_progress=on_progress,
            cancel=cancel,
            on_process=on_process,
        )

        # Verification
        v_res = verify_output(
            src_meta=meta,
            out_path=str(tmp),
            profile=PROFILES["phone_compatible"],
        )
        if v_res.is_valid and not cancel():
            tmp.replace(dst)
            if on_progress:
                on_progress(1.0)
            return True

        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False

    except Exception as e:
        logger.error("fix_faststart failed for %s: %s", src, e)
        return False


def transcode_to_compatible(
    src: str,
    dst: str,
    profile: Optional[EncodingProfile] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Callable[[], bool] = lambda: False,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> bool:
    """Transcode src -> dst according to profile.
    Writes to a temporary file first and atomically renames only on verified success.
    """
    config.ffmpeg_path = FFMPEG
    config.ffprobe_path = FFPROBE

    try:
        meta = probe_media(src, ffprobe_bin=FFPROBE)
        target_profile = profile or PROFILES["phone_compatible"]
        tmp = transcode_file(
            src=src,
            dst=dst,
            meta=meta,
            profile=target_profile,
            on_progress=on_progress,
            cancel=cancel,
            on_process=on_process,
        )

        v_res = verify_output(
            src_meta=meta,
            out_path=str(tmp),
            profile=target_profile,
        )
        if v_res.is_valid and not cancel():
            tmp.replace(dst)
            if on_progress:
                on_progress(1.0)
            return True

        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False

    except Exception as e:
        logger.error("transcode_to_compatible failed for %s: %s", src, e)
        return False


def collect(paths: List[str]) -> List[str]:
    """Collect all valid media files from list of files and folders."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, filenames in os.walk(p):
                for name in sorted(filenames):
                    if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                        files.append(os.path.join(root, name))
        elif os.path.isfile(p):
            files.append(p)
    return files


def main():
    ap = argparse.ArgumentParser(
        description="AI-Assisted Video Fixer & Transcoder for Windows."
    )
    ap.add_argument("paths", nargs="+", help="One or more video files or folders")
    ap.add_argument("--outdir", help="Output directory (default: next to source)")
    ap.add_argument("--suffix", default="_fixed", help="Filename suffix for output")
    ap.add_argument("--check-only", action="store_true", help="Inspect and report status without processing")
    ap.add_argument(
        "--profile",
        default="phone_compatible",
        choices=list(PROFILES.keys()),
        help="Target compatibility profile",
    )
    ap.add_argument("--ai", action="store_true", help="Enable Gemini AI diagnostic analysis")
    ap.add_argument("--remux-only", action="store_true", help="Force remux only (skip transcoding)")
    args = ap.parse_args()

    global FFMPEG, FFPROBE
    FFMPEG = config.ffmpeg_path
    FFPROBE = config.ffprobe_path

    if not FFMPEG or not FFPROBE:
        sys.exit("Error: FFmpeg/FFprobe binaries not found on PATH or next to executable.")

    files = collect(args.paths)
    if not files:
        print("No valid video files found in specified paths.")
        return

    profile = PROFILES.get(args.profile, PROFILES["phone_compatible"])
    print(f"\nTarget profile: {profile.name} ({profile.description})")
    print(f"Discovered {len(files)} file(s) for processing.\n" + "=" * 60)

    for src in files:
        try:
            meta = probe_media(src, ffprobe_bin=FFPROBE)
            analysis = analyze_media(meta, profile=profile)

            ai_advice = ""
            if args.ai:
                ai_rec, _ = query_gemini_diagnostics(meta, analysis)
                if ai_rec:
                    analysis = validate_and_apply_ai_recommendation(ai_rec, analysis)
                    ai_advice = f" | AI: {ai_rec.action} ({ai_rec.confidence * 100:.0f}%)"

            print(
                f"[{analysis.status.upper():<16}] {os.path.basename(src)}  "
                f"({meta.vcodec}/{meta.pix_fmt}, {meta.duration:.1f}s){ai_advice}"
            )
            if analysis.reasons:
                for r in analysis.reasons:
                    print(f"   -> {r}")

            if args.check_only:
                continue

            if analysis.status == "ok":
                print("   Status is already OK. Skipping.\n")
                continue

            if analysis.status in ("corrupt", "unknown"):
                print("   File cannot be safely processed automatically. Skipping.\n")
                continue

            # Determine destination path
            stem, ext = os.path.splitext(os.path.basename(src))
            out_folder = args.outdir or os.path.dirname(os.path.abspath(src))
            dst = os.path.join(out_folder, f"{stem}{args.suffix}.{profile.target_container}")

            if os.path.abspath(src) == os.path.abspath(dst):
                print("   ERROR: Source and destination paths are identical. Skipping.\n")
                continue

            # Process based on required action
            progress_fn = lambda p: print(f"\r   Progress: {p * 100:5.1f}%", end="", flush=True)

            if analysis.action == "remux" or args.remux_only:
                print(f"   Remuxing (+faststart)...")
                ok = fix_faststart(src, dst, on_progress=progress_fn)
            elif analysis.action == "transcode":
                print(f"   Transcoding to {profile.name}...")
                ok = transcode_to_compatible(src, dst, profile=profile, on_progress=progress_fn)
            else:
                print(f"   Action '{analysis.action}' requires manual review. Skipping.")
                continue

            if ok:
                print(f"\n   [SUCCESS] Saved to: {dst}\n")
            else:
                print(f"\n   [FAILED] Could not verify or process file.\n")

        except Exception as e:
            print(f"[ERR ] {src}: {e}\n")


if __name__ == "__main__":
    main()
