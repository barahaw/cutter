"""Tests for multi-stage output verification."""

from pathlib import Path
from src.config import PROFILES
from src.media_probe import probe_media
from src.verification import run_decode_test, verify_output


def test_verify_valid_output(sample_h264_faststart: Path):
    src_meta = probe_media(str(sample_h264_faststart))
    res = verify_output(
        src_meta=src_meta,
        out_path=str(sample_h264_faststart),
        profile=PROFILES["phone_compatible"],
        run_decode=True,
    )
    assert res.is_valid is True
    assert res.faststart_ok is True
    assert res.decode_test_passed is True
    assert len(res.errors) == 0


def test_verify_no_faststart_fails(sample_h264_no_faststart: Path):
    src_meta = probe_media(str(sample_h264_no_faststart))
    res = verify_output(
        src_meta=src_meta,
        out_path=str(sample_h264_no_faststart),
        profile=PROFILES["phone_compatible"],
        run_decode=False,
    )
    assert res.is_valid is False
    assert any("Faststart check failed" in err for err in res.errors)


def test_verify_nonexistent_file(sample_h264_faststart: Path):
    src_meta = probe_media(str(sample_h264_faststart))
    res = verify_output(
        src_meta=src_meta,
        out_path="nonexistent_output_file.mp4",
        profile=PROFILES["phone_compatible"],
    )
    assert res.is_valid is False
    assert any("does not exist" in err for err in res.errors)


def test_verify_empty_file(sample_h264_faststart: Path, temp_dir: Path):
    empty_file = temp_dir / "empty.mp4"
    empty_file.write_bytes(b"")
    src_meta = probe_media(str(sample_h264_faststart))
    res = verify_output(
        src_meta=src_meta,
        out_path=str(empty_file),
        profile=PROFILES["phone_compatible"],
    )
    assert res.is_valid is False
    assert any("suspiciously small or empty" in err for err in res.errors)


def test_decode_test_on_valid_file(sample_h264_faststart: Path):
    passed, err = run_decode_test(str(sample_h264_faststart))
    assert passed is True
    assert err is None
