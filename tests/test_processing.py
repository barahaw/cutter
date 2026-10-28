"""Tests for FFmpeg remuxing and transcoding execution."""

from pathlib import Path
import pytest

from src.config import PROFILES
from src.processing import (
    ProcessingError,
    prepare_destination,
    remux_file,
    transcode_file,
)


def test_prepare_destination_identical_path(sample_h264_faststart: Path):
    with pytest.raises(ValueError, match="Destination path must not be identical"):
        prepare_destination(str(sample_h264_faststart), str(sample_h264_faststart))


def test_prepare_destination_creates_temp(sample_h264_faststart: Path, temp_dir: Path):
    dst = temp_dir / "output.mp4"
    dst_path, temp_path = prepare_destination(str(sample_h264_faststart), str(dst))
    assert dst_path == dst.resolve()
    assert temp_path.parent == dst_path.parent
    assert ".part_" in temp_path.name


def test_remux_file_execution(sample_h264_no_faststart: Path, temp_dir: Path):
    dst = temp_dir / "remuxed.mp4"
    temp_out = remux_file(str(sample_h264_no_faststart), str(dst))
    assert temp_out.is_file()
    assert temp_out.stat().st_size > 0


def test_transcode_file_execution(sample_hevc_video: Path, temp_dir: Path):
    dst = temp_dir / "transcoded.mp4"
    temp_out = transcode_file(
        src=str(sample_hevc_video),
        dst=str(dst),
        profile=PROFILES["phone_compatible"],
    )
    assert temp_out.is_file()
    assert temp_out.stat().st_size > 0


def test_processing_cancellation(sample_hevc_video: Path, temp_dir: Path):
    dst = temp_dir / "cancelled.mp4"
    # Immediately cancelled
    with pytest.raises(ProcessingError, match="cancelled"):
        transcode_file(
            src=str(sample_hevc_video),
            dst=str(dst),
            cancel=lambda: True,
        )
    assert not dst.exists()
