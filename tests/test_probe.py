"""Tests for media probing and MP4 atom scanning."""

import os
from pathlib import Path
import pytest

from src.media_probe import (
    has_faststart,
    parse_frame_rate,
    probe_media,
    top_level_atoms,
)


def test_parse_frame_rate():
    assert parse_frame_rate("30/1") == 30.0
    assert parse_frame_rate("24000/1001") == 23.976
    assert parse_frame_rate("25") == 25.0
    assert parse_frame_rate("0/0") == 0.0
    assert parse_frame_rate(None) == 0.0
    assert parse_frame_rate("invalid") == 0.0


def test_atom_scanning_faststart(sample_h264_faststart: Path):
    atoms = top_level_atoms(str(sample_h264_faststart))
    atom_names = [name for name, _, _ in atoms]
    assert "moov" in atom_names
    assert "mdat" in atom_names

    # Faststart: moov should precede mdat
    moov_idx = atom_names.index("moov")
    mdat_idx = atom_names.index("mdat")
    assert moov_idx < mdat_idx
    assert has_faststart(str(sample_h264_faststart)) is True


def test_atom_scanning_no_faststart(sample_h264_no_faststart: Path):
    assert has_faststart(str(sample_h264_no_faststart)) is False


def test_probe_media_metadata(sample_h264_faststart: Path):
    meta = probe_media(str(sample_h264_faststart))
    assert meta.probe_error is None
    assert meta.duration > 0.8
    assert meta.has_faststart is True
    assert len(meta.video_streams) == 1
    assert meta.vcodec == "h264"
    assert meta.pix_fmt == "yuv420p"
    assert len(meta.audio_streams) == 1
    assert meta.audio_streams[0].codec_name == "aac"
    assert meta.has_audio is True


def test_probe_nonexistent_file():
    with pytest.raises(FileNotFoundError):
        probe_media("nonexistent_video_file_xyz123.mp4")


def test_probe_corrupted_file(temp_dir: Path):
    corrupt_file = temp_dir / "corrupted.mp4"
    corrupt_file.write_bytes(b"NOT_A_VALID_MP4_HEADER_GARBAGE_DATA")
    meta = probe_media(str(corrupt_file))
    assert meta.probe_error is not None
