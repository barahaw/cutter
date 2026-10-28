"""Tests for Gemini AI diagnostic validation, schema validation, and fallback mechanisms."""

import pytest
from pydantic import ValidationError

from src.ai_analyzer import (
    AIRecommendation,
    build_probe_summary,
    query_gemini_diagnostics,
    validate_and_apply_ai_recommendation,
)
from src.config import config
from src.media_analyzer import ClassificationResult
from src.media_probe import (
    AudioStreamInfo,
    MediaMetadata,
    VideoStreamInfo,
)


def test_ai_recommendation_schema_valid():
    data = {
        "action": "remux",
        "confidence": 0.95,
        "compatibility_assessment": "Streams are valid H.264/AAC, moov atom needs to be moved to the beginning.",
        "reasoning": "Faststart can be achieved with zero re-encoding loss via stream copying.",
        "recommended_profile": "phone_compatible",
        "uncertainty_notes": None,
    }
    rec = AIRecommendation(**data)
    assert rec.action == "remux"
    assert rec.confidence == 0.95


def test_ai_recommendation_schema_invalid_action():
    data = {
        "action": "arbitrary_shell_command",
        "confidence": 0.9,
        "compatibility_assessment": "unknown",
        "reasoning": "invalid",
    }
    with pytest.raises(ValidationError):
        AIRecommendation(**data)


def test_ai_recommendation_schema_invalid_confidence():
    data = {
        "action": "remux",
        "confidence": 1.5,  # must be <= 1.0
        "compatibility_assessment": "unknown",
        "reasoning": "invalid",
    }
    with pytest.raises(ValidationError):
        AIRecommendation(**data)


def test_build_probe_summary_privacy():
    meta = MediaMetadata(
        path="C:/Users/SecretUser/Videos/private_home_video.mp4",
        filename="private_home_video.mp4",
        container_format="mov,mp4",
        duration=120.0,
        size_bytes=1000000,
        has_faststart=False,
        video_streams=[VideoStreamInfo(codec_name="h264", width=1920, height=1080, pix_fmt="yuv420p")],
        audio_streams=[AudioStreamInfo(codec_name="aac", channels=2, sample_rate=48000)],
    )
    det = ClassificationResult(status="needs-remux", action="remux")
    summary = build_probe_summary(meta, det)

    # Full filepath should NOT be in the summary sent to the API
    assert "C:/Users/SecretUser/Videos" not in str(summary)
    assert summary["container"] == "mov,mp4"
    assert summary["duration_sec"] == 120.0


def test_validate_ai_cannot_downgrade_transcode_to_remux():
    det = ClassificationResult(
        status="needs-transcode",
        action="transcode",
        needs_video_transcode=True,
        reasons=["Video codec 'hevc' incompatible with phone_compatible profile"],
    )
    ai_bad_rec = AIRecommendation(
        action="remux",
        confidence=0.9,
        compatibility_assessment="I think it works fine",
        reasoning="Just copy streams",
    )
    # Validator should override the AI's unsafe downgrade
    final = validate_and_apply_ai_recommendation(ai_bad_rec, det)
    assert final.action == "transcode"
    assert final.status == "needs-transcode"
    assert any("overridden by required transcoding" in r for r in final.reasons)


def test_validate_ai_cannot_override_corrupt_file():
    det = ClassificationResult(
        status="corrupt",
        action="manual_review",
        reasons=["File inspection failed: Invalid data found"],
    )
    ai_bad_rec = AIRecommendation(
        action="no_action",
        confidence=0.85,
        compatibility_assessment="Looks fine to me",
        reasoning="Ignore corruption",
    )
    final = validate_and_apply_ai_recommendation(ai_bad_rec, det)
    assert final.status == "corrupt"
    assert final.action == "manual_review"


def test_validate_ai_applies_valid_guidance():
    det = ClassificationResult(
        status="needs-remux",
        action="remux",
        reasons=["MP4 index is at end of file"],
    )
    ai_rec = AIRecommendation(
        action="remux",
        confidence=0.95,
        compatibility_assessment="H.264 stream is valid, only atom relocation needed",
        reasoning="Stream copying with +faststart preserves quality while enabling instant mobile playback.",
        recommended_profile="phone_compatible",
    )
    final = validate_and_apply_ai_recommendation(ai_rec, det)
    assert final.action == "remux"
    assert any("Stream copying with +faststart" in r for r in final.reasons)


def test_ai_fallback_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "gemini_api_key", "")
    meta = MediaMetadata(path="test.mp4", filename="test.mp4")
    det = ClassificationResult(status="ok", action="no_action")
    rec, err = query_gemini_diagnostics(meta, det)
    assert rec is None
    assert "GEMINI_API_KEY is not configured" in err
