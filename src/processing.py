"""FFmpeg processing engine for remuxing and transcoding video files."""

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.config import EncodingProfile, PROFILES, config
from src.logging_config import logger
from src.media_probe import MediaMetadata, probe_media

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ProcessingError(Exception):
    """Custom exception raised when video processing fails."""
    pass


def prepare_destination(src: str, dst: str) -> Tuple[Path, Path]:
    """Validate destination, check free disk space, and prepare temporary file path."""
    src_path = Path(src).resolve()
    dst_path = Path(dst).resolve()

    if src_path == dst_path:
        raise ValueError("Destination path must not be identical to source path.")

    out_dir = dst_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Estimate required disk space (source size + 10% safety margin)
    src_size = src_path.stat().st_size
    needed_space = int(src_size * 1.10)
    free_space = shutil.disk_usage(out_dir).free

    if free_space < needed_space:
        raise ProcessingError(
            f"Insufficient disk space in '{out_dir}'. Need ~{needed_space // (1024*1024)}MB, available: {free_space // (1024*1024)}MB"
        )

    # Unique temporary file to avoid collisions
    temp_filename = f"{dst_path.stem}.part_{uuid.uuid4().hex[:8]}{dst_path.suffix}"
    temp_path = out_dir / temp_filename
    return dst_path, temp_path


def build_subtitle_args(meta: MediaMetadata, target_container: str = "mp4") -> List[str]:
    """Build subtitle stream mapping and codec arguments according to container compatibility."""
    if not meta.subtitle_streams:
        return []

    args: List[str] = []
    has_compatible_sub = False

    for sub in meta.subtitle_streams:
        # MP4 containers only support text subtitles via mov_text
        if target_container == "mp4":
            if sub.codec_name in {"mov_text", "subrip", "srt", "text"}:
                has_compatible_sub = True
            else:
                logger.info(
                    "Dropping incompatible bitmap/ass subtitle stream #%d (%s) for MP4 output.",
                    sub.index,
                    sub.codec_name
                )
        else:
            has_compatible_sub = True

    if has_compatible_sub:
        args.extend(["-map", "0:s?"])
        if target_container == "mp4":
            args.extend(["-c:s", "mov_text"])
        else:
            args.extend(["-c:s", "copy"])

    return args


def run_ffmpeg_command(
    cmd: List[str],
    total_duration: float,
    temp_path: Path,
    dst_path: Path,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Callable[[], bool] = lambda: False,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> bool:
    """Execute FFmpeg process with live progress streaming, cancellation, and atomic swap."""
    logger.debug("Executing FFmpeg command: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )

    if on_process is not None:
        on_process(proc)

    stderr_output: List[str] = []

    try:
        if proc.stdout:
            for line in proc.stdout:
                if cancel():
                    proc.kill()
                    break

                if line.startswith(("out_time_us=", "out_time_ms=")) and total_duration > 0 and on_progress:
                    try:
                        val = int(line.split("=")[1].strip())
                        # out_time_ms is in microseconds in modern ffmpeg progress pipe
                        secs = val / 1_000_000 if line.startswith("out_time_us") or val > 1_000_000 else val / 1_000
                        fraction = min(secs / total_duration, 0.99)
                        on_progress(max(fraction, 0.0))
                    except (ValueError, IndexError):
                        pass

        _, stderr_data = proc.communicate()
        if stderr_data:
            stderr_output.append(stderr_data)

    finally:
        if proc.poll() is None:
            proc.kill()

    if cancel():
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return False

    if proc.returncode != 0 or not temp_path.exists():
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        err_msg = "".join(stderr_output).strip()
        logger.error("FFmpeg execution failed (code %d): %s", proc.returncode, err_msg[-500:] if err_msg else "Unknown")
        raise ProcessingError(f"FFmpeg process failed with exit code {proc.returncode}: {err_msg[-300:]}")

    return True


def remux_file(
    src: str,
    dst: str,
    meta: Optional[MediaMetadata] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Callable[[], bool] = lambda: False,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> Path:
    """Fast remux file using stream copying and +faststart flag for MP4."""
    ffmpeg = config.ffmpeg_path
    if not ffmpeg or not os.path.isfile(ffmpeg):
        raise RuntimeError("FFmpeg executable not found.")

    if meta is None:
        meta = probe_media(src)

    dst_path, temp_path = prepare_destination(src, dst)
    sub_args = build_subtitle_args(meta, target_container="mp4")

    cmd = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-v", "error",
        "-nostats",
        "-progress", "pipe:1",
        "-i", src,
        "-map", "0:v",
        "-map", "0:a?",
    ]
    cmd.extend(sub_args)
    cmd.extend([
        "-c", "copy",
        "-movflags", "+faststart",
        str(temp_path),
    ])

    success = run_ffmpeg_command(
        cmd=cmd,
        total_duration=meta.duration,
        temp_path=temp_path,
        dst_path=dst_path,
        on_progress=on_progress,
        cancel=cancel,
        on_process=on_process,
    )

    if not success:
        raise ProcessingError("Remux operation cancelled or failed.")

    return temp_path


def transcode_file(
    src: str,
    dst: str,
    meta: Optional[MediaMetadata] = None,
    profile: Optional[EncodingProfile] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel: Callable[[], bool] = lambda: False,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> Path:
    """Transcode file using safe, compatible software encoding (libx264 + aac)."""
    ffmpeg = config.ffmpeg_path
    if not ffmpeg or not os.path.isfile(ffmpeg):
        raise RuntimeError("FFmpeg executable not found.")

    if meta is None:
        meta = probe_media(src)

    target = profile or PROFILES["phone_compatible"]
    dst_path, temp_path = prepare_destination(src, dst)

    # Video filters for scaling & frame rate constraints if needed
    vf_filters: List[str] = []
    if target.max_width or target.max_height:
        mw = target.max_width or -2
        mh = target.max_height or -2
        # Scale down while maintaining aspect ratio and ensuring even dimensions
        vf_filters.append(f"scale='min({mw},iw)':'-2'")
    if target.max_fps and meta.video_streams and meta.video_streams[0].frame_rate > target.max_fps:
        vf_filters.append(f"fps={target.max_fps}")

    # Explicit pixel format
    pix_fmt = target.allowed_pix_fmts[0] if target.allowed_pix_fmts else "yuv420p"

    sub_args = build_subtitle_args(meta, target_container="mp4")

    cmd = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-v", "error",
        "-nostats",
        "-progress", "pipe:1",
        "-i", src,
        "-map", "0:v:0",
        "-map", "0:a?",
    ]
    cmd.extend(sub_args)

    # Video encoding params
    cmd.extend([
        "-c:v", target.video_codec,
        "-preset", target.preset,
        "-crf", str(target.crf),
        "-pix_fmt", pix_fmt,
    ])
    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    # Audio encoding params
    # If source has no audio, -map 0:a? handles it safely
    cmd.extend([
        "-c:a", target.audio_codec,
        "-b:a", target.audio_bitrate,
    ])

    if target.require_faststart:
        cmd.extend(["-movflags", "+faststart"])

    cmd.append(str(temp_path))

    success = run_ffmpeg_command(
        cmd=cmd,
        total_duration=meta.duration,
        temp_path=temp_path,
        dst_path=dst_path,
        on_progress=on_progress,
        cancel=cancel,
        on_process=on_process,
    )

    if not success:
        raise ProcessingError("Transcode operation cancelled or failed.")

    return temp_path
