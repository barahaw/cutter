"""Tests for deterministic classification logic and profile matching."""

from pathlib import Path
from src.config import PROFILES
from src.media_analyzer import analyze_media
from src.media_probe import (
    AudioStreamInfo,
    MediaMetadata,
    VideoStreamInfo,
    probe_media,
)


def test_classify_valid_faststart(sample_h264_faststart: Path):
    meta = probe_media(str(sample_h264_faststart))
    result = analyze_media(meta, profile=PROFILES["phone_compatible"])
    assert result.status == "ok"
    assert result.action == "no_action"
    assert not result.needs_faststart_fix
    assert not result.needs_video_transcode


def test_classify_needs_remux(sample_h264_no_faststart: Path):
    meta = probe_media(str(sample_h264_no_faststart))
    result = analyze_media(meta, profile=PROFILES["phone_compatible"])
    assert result.status == "needs-remux"
    assert result.action == "remux"
    assert result.needs_faststart_fix is True
    assert result.needs_video_transcode is False


def test_classify_hevc_needs_transcode(sample_hevc_video: Path):
    meta = probe_media(str(sample_hevc_video))
    result = analyze_media(meta, profile=PROFILES["phone_compatible"])
    assert result.status == "needs-transcode"
    assert result.action == "transcode"
    assert result.needs_video_transcode is True
    assert any("codec 'hevc' incompatible" in r for r in result.reasons)


def test_classify_10bit_pixel_format():
    meta = MediaMetadata(
        path="dummy.mp4",
        filename="dummy.mp4",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        duration=10.0,
        size_bytes=5000000,
        has_faststart=True,
        video_streams=[
            VideoStreamInfo(
                codec_name="h264",
                profile="High 10",
                width=1920,
                height=1080,
                pix_fmt="yuv420p10le",
                frame_rate=30.0,
            )
        ],
        audio_streams=[
            AudioStreamInfo(codec_name="aac", channels=2, sample_rate=48000)
        ],
    )
    result = analyze_media(meta, profile=PROFILES["phone_compatible"])
    assert result.status == "needs-transcode"
    assert result.needs_video_transcode is True
    assert any("yuv420p10le" in r for r in result.reasons)


def test_classify_incompatible_audio():
    meta = MediaMetadata(
        path="dummy.mp4",
        filename="dummy.mp4",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        duration=10.0,
        size_bytes=5000000,
        has_faststart=True,
        video_streams=[
            VideoStreamInfo(
                codec_name="h264",
                profile="High",
                width=1920,
                height=1080,
                pix_fmt="yuv420p",
                frame_rate=30.0,
            )
        ],
        audio_streams=[
            AudioStreamInfo(codec_name="ac3", channels=6, sample_rate=48000)
        ],
    )
    result = analyze_media(meta, profile=PROFILES["phone_compatible"])
    assert result.status == "needs-transcode"
    assert result.needs_audio_transcode is True
    assert any("ac3" in r for r in result.reasons)


def test_classify_corrupted_media():
    meta = MediaMetadata(
        path="corrupted.mp4",
        filename="corrupted.mp4",
        probe_error="Invalid data found when processing input",
    )
    result = analyze_media(meta, profile=PROFILES["phone_compatible"])
    assert result.status == "corrupt"
    assert result.action == "manual_review"
