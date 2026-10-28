"""Media inspection using MP4 atom scanning and FFprobe."""

import json
import os
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import config
from src.logging_config import logger

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".ts", ".webm"}


# ---------------- MP4 Atom Scanning ----------------

def top_level_atoms(path: str) -> List[Tuple[str, int, int]]:
    """Return [(name, offset, size)] for top-level MP4 atoms. Reads headers only."""
    atoms = []
    if not os.path.isfile(path):
        return atoms
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= file_size:
            f.seek(pos)
            header = f.read(8)
            if len(header) < 8:
                break
            size, name = struct.unpack(">I4s", header)
            if size == 1:  # 64-bit size follows
                extra = f.read(8)
                if len(extra) < 8:
                    break
                size = struct.unpack(">Q", extra)[0]
            elif size == 0:  # atom runs to end of file
                size = file_size - pos
            if size < 8:  # corrupt header, stop
                break
            atoms.append((name.decode("latin-1", errors="replace"), pos, size))
            pos += size
    return atoms


def has_faststart(path: str) -> Optional[bool]:
    """True if moov comes before mdat, False if after, None if unknown or not MP4."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in {".mp4", ".m4v", ".mov"}:
        return None
    moov = mdat = None
    try:
        for name, offset, _ in top_level_atoms(path):
            if name == "moov" and moov is None:
                moov = offset
            elif name == "mdat" and mdat is None:
                mdat = offset
    except Exception as e:
        logger.debug("Failed parsing atoms for %s: %e", path, e)
        return None

    if moov is None or mdat is None:
        return None
    return moov < mdat


# ---------------- FFprobe Inspection ----------------

@dataclass
class VideoStreamInfo:
    index: int = 0
    codec_name: str = ""
    profile: Optional[str] = None
    level: Optional[int] = None
    width: int = 0
    height: int = 0
    pix_fmt: str = ""
    frame_rate: float = 0.0
    bit_rate: Optional[int] = None
    bits_per_raw_sample: Optional[int] = None
    is_hdr: bool = False
    color_transfer: Optional[str] = None


@dataclass
class AudioStreamInfo:
    index: int = 0
    codec_name: str = ""
    profile: Optional[str] = None
    sample_rate: int = 0
    channels: int = 0
    channel_layout: Optional[str] = None
    bit_rate: Optional[int] = None
    language: Optional[str] = None
    title: Optional[str] = None


@dataclass
class SubtitleStreamInfo:
    index: int = 0
    codec_name: str = ""
    language: Optional[str] = None
    title: Optional[str] = None
    is_default: bool = False
    is_forced: bool = False


@dataclass
class MediaMetadata:
    path: str
    filename: str
    container_format: str = ""
    duration: float = 0.0
    size_bytes: int = 0
    bit_rate: int = 0
    has_faststart: Optional[bool] = None
    video_streams: List[VideoStreamInfo] = field(default_factory=list)
    audio_streams: List[AudioStreamInfo] = field(default_factory=list)
    subtitle_streams: List[SubtitleStreamInfo] = field(default_factory=list)
    other_streams_count: int = 0
    probe_error: Optional[str] = None

    # Backward compatibility helpers
    @property
    def vcodec(self) -> str:
        return self.video_streams[0].codec_name if self.video_streams else ""

    @property
    def profile(self) -> Optional[str]:
        return self.video_streams[0].profile if self.video_streams else None

    @property
    def pix_fmt(self) -> str:
        return self.video_streams[0].pix_fmt if self.video_streams else ""

    @property
    def has_audio(self) -> bool:
        return len(self.audio_streams) > 0

    @property
    def extra_streams(self) -> int:
        return len(self.subtitle_streams) + self.other_streams_count

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["vcodec"] = self.vcodec
        d["profile"] = self.profile
        d["pix_fmt"] = self.pix_fmt
        d["has_audio"] = self.has_audio
        d["extra_streams"] = self.extra_streams
        return d


def parse_frame_rate(rate_str: Optional[str]) -> float:
    """Converts strings like '30000/1001' or '24' to float."""
    if not rate_str or rate_str == "0/0":
        return 0.0
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/", 1)
            num_f, den_f = float(num), float(den)
            return round(num_f / den_f, 3) if den_f != 0 else 0.0
        return round(float(rate_str), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_media(path: str, ffprobe_bin: Optional[str] = None) -> MediaMetadata:
    """Extract comprehensive structured metadata for a media file via FFprobe."""
    ffprobe = ffprobe_bin or config.ffprobe_path
    if not ffprobe or not os.path.isfile(ffprobe):
        raise RuntimeError("ffprobe executable not found or not configured.")

    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    filename = os.path.basename(path)
    file_size = os.path.getsize(path)
    faststart = has_faststart(path)

    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_error",
        path,
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.error("ffprobe timed out on %s", path)
        return MediaMetadata(
            path=path,
            filename=filename,
            size_bytes=file_size,
            has_faststart=faststart,
            probe_error="ffprobe timed out after 30 seconds"
        )
    except Exception as e:
        logger.error("ffprobe execution failed on %s: %s", path, e)
        return MediaMetadata(
            path=path,
            filename=filename,
            size_bytes=file_size,
            has_faststart=faststart,
            probe_error=str(e)
        )

    if res.returncode != 0:
        err_msg = res.stderr.strip() or "ffprobe exited with non-zero status"
        return MediaMetadata(
            path=path,
            filename=filename,
            size_bytes=file_size,
            has_faststart=faststart,
            probe_error=err_msg
        )

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        return MediaMetadata(
            path=path,
            filename=filename,
            size_bytes=file_size,
            has_faststart=faststart,
            probe_error=f"Malformed ffprobe JSON output: {e}"
        )

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = 0.0
    try:
        duration = float(fmt.get("duration") or 0.0)
    except ValueError:
        pass

    bit_rate = 0
    try:
        bit_rate = int(fmt.get("bit_rate") or 0)
    except ValueError:
        pass

    video_streams: List[VideoStreamInfo] = []
    audio_streams: List[AudioStreamInfo] = []
    subtitle_streams: List[SubtitleStreamInfo] = []
    other_streams_count = 0

    for s in streams:
        c_type = s.get("codec_type")
        idx = int(s.get("index", 0))
        c_name = s.get("codec_name", "")
        tags = s.get("tags", {})
        disp = s.get("disposition", {})

        if c_type == "video":
            # Some container attachments are reported as video, check codec
            if c_name in {"mjpeg", "png"} and disp.get("attached_pic", 0) == 1:
                other_streams_count += 1
                continue

            fps = parse_frame_rate(s.get("avg_frame_rate") or s.get("r_frame_rate"))
            color_trc = s.get("color_transfer", "")
            is_hdr = color_trc in {"smpte2084", "arib-std-b67"} or "hdr" in (s.get("color_primaries") or "").lower()

            bits_raw = None
            if s.get("bits_per_raw_sample"):
                try:
                    bits_raw = int(s.get("bits_per_raw_sample"))
                except ValueError:
                    pass

            v_bitrate = None
            if s.get("bit_rate"):
                try:
                    v_bitrate = int(s.get("bit_rate"))
                except ValueError:
                    pass

            video_streams.append(
                VideoStreamInfo(
                    index=idx,
                    codec_name=c_name,
                    profile=s.get("profile"),
                    level=s.get("level"),
                    width=int(s.get("width") or 0),
                    height=int(s.get("height") or 0),
                    pix_fmt=s.get("pix_fmt", ""),
                    frame_rate=fps,
                    bit_rate=v_bitrate,
                    bits_per_raw_sample=bits_raw,
                    is_hdr=is_hdr,
                    color_transfer=color_trc,
                )
            )
        elif c_type == "audio":
            a_bitrate = None
            if s.get("bit_rate"):
                try:
                    a_bitrate = int(s.get("bit_rate"))
                except ValueError:
                    pass

            audio_streams.append(
                AudioStreamInfo(
                    index=idx,
                    codec_name=c_name,
                    profile=s.get("profile"),
                    sample_rate=int(s.get("sample_rate") or 0),
                    channels=int(s.get("channels") or 0),
                    channel_layout=s.get("channel_layout"),
                    bit_rate=a_bitrate,
                    language=tags.get("language"),
                    title=tags.get("title"),
                )
            )
        elif c_type == "subtitle":
            subtitle_streams.append(
                SubtitleStreamInfo(
                    index=idx,
                    codec_name=c_name,
                    language=tags.get("language"),
                    title=tags.get("title"),
                    is_default=bool(disp.get("default", 0)),
                    is_forced=bool(disp.get("forced", 0)),
                )
            )
        else:
            other_streams_count += 1

    return MediaMetadata(
        path=path,
        filename=filename,
        container_format=fmt.get("format_name", ""),
        duration=duration,
        size_bytes=file_size,
        bit_rate=bit_rate,
        has_faststart=faststart,
        video_streams=video_streams,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        other_streams_count=other_streams_count,
    )
