"""Shared pytest fixtures including synthetic media generation using FFmpeg."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator
import pytest

from src.config import config

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@pytest.fixture(scope="session")
def ffmpeg_bin() -> str:
    bin_path = config.ffmpeg_path
    if not bin_path or not os.path.isfile(bin_path):
        pytest.skip("FFmpeg executable not available for media tests.")
    return bin_path


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def sample_h264_faststart(temp_dir: Path, ffmpeg_bin: str) -> Path:
    """Creates a 1-second H.264/AAC MP4 with +faststart (moov before mdat)."""
    out_file = temp_dir / "valid_faststart.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        str(out_file),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    return out_file


@pytest.fixture
def sample_h264_no_faststart(temp_dir: Path, ffmpeg_bin: str) -> Path:
    """Creates a 1-second H.264/AAC MP4 with moov atom at the end (no faststart)."""
    out_file = temp_dir / "no_faststart.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "64k",
        str(out_file),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    return out_file


@pytest.fixture
def sample_hevc_video(temp_dir: Path, ffmpeg_bin: str) -> Path:
    """Creates a 1-second HEVC (H.265) MP4 file requiring re-encoding for phone compatibility."""
    out_file = temp_dir / "hevc_video.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-c:v", "libx265", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_file),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    return out_file


@pytest.fixture
def sample_unicode_path(temp_dir: Path, ffmpeg_bin: str) -> Path:
    """Creates a media file with no faststart in a directory path containing spaces and non-ASCII characters."""
    unicode_dir = temp_dir / "فيديو تجريبي Special - 2026"
    unicode_dir.mkdir(parents=True, exist_ok=True)
    out_file = unicode_dir / "مقطع_اختبار_clip.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_file),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    return out_file
