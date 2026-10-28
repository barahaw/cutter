"""Tests for batch processing, source file safety, and Unicode paths."""

from pathlib import Path
from src.batch_processor import BatchProcessor
from src.config import PROFILES
from src.media_probe import probe_media


def test_batch_processor_end_to_end_remux(sample_h264_no_faststart: Path, temp_dir: Path):
    out_dir = temp_dir / "fixed_output"
    processor = BatchProcessor(
        profile=PROFILES["phone_compatible"],
        out_dir=str(out_dir),
        suffix="_repaired",
        use_ai=False,
    )

    orig_mtime = sample_h264_no_faststart.stat().st_mtime
    orig_size = sample_h264_no_faststart.stat().st_size

    job = processor.process_file(str(sample_h264_no_faststart))
    assert job.status == "completed"
    assert job.action_taken == "remux"
    assert job.destination_path is not None

    dst_path = Path(job.destination_path)
    assert dst_path.is_file()
    assert dst_path.stat().st_size > 0

    # SAFETY CHECK: Source file must remain completely untouched!
    assert sample_h264_no_faststart.stat().st_mtime == orig_mtime
    assert sample_h264_no_faststart.stat().st_size == orig_size

    # Check verified output has faststart
    out_meta = probe_media(str(dst_path))
    assert out_meta.has_faststart is True


def test_batch_processor_end_to_end_transcode(sample_hevc_video: Path, temp_dir: Path):
    out_dir = temp_dir / "transcoded_output"
    processor = BatchProcessor(
        profile=PROFILES["phone_compatible"],
        out_dir=str(out_dir),
        suffix="_transcoded",
        use_ai=False,
    )

    job = processor.process_file(str(sample_hevc_video))
    assert job.status == "completed"
    assert job.action_taken == "transcode"

    dst_path = Path(job.destination_path)
    assert dst_path.is_file()

    out_meta = probe_media(str(dst_path))
    # Transcoded video must now be H.264
    assert out_meta.vcodec == "h264"
    assert out_meta.has_faststart is True


def test_batch_processor_unicode_paths(sample_unicode_path: Path, temp_dir: Path):
    out_dir = temp_dir / "مجلد الإخراج Output"
    processor = BatchProcessor(
        profile=PROFILES["phone_compatible"],
        out_dir=str(out_dir),
        use_ai=False,
    )

    job = processor.process_file(str(sample_unicode_path))
    assert job.status == "completed"
    assert Path(job.destination_path).exists()
