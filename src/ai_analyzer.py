"""Gemini API integration for AI-assisted video diagnostics and safe recommendations."""

import json
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel, Field, ValidationError

from src.config import config
from src.logging_config import logger
from src.media_analyzer import ClassificationResult
from src.media_probe import MediaMetadata


class AIRecommendation(BaseModel):
    """Strict schema for Gemini diagnostic recommendations."""
    action: str = Field(
        ...,
        pattern="^(no_action|remux|transcode|manual_review)$",
        description="One of: no_action, remux, transcode, manual_review",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0",
    )
    compatibility_assessment: str = Field(
        ...,
        description="Concise assessment of target device compatibility",
    )
    reasoning: str = Field(
        ...,
        description="Technical justification for the recommended action",
    )
    recommended_profile: Optional[str] = Field(
        default="phone_compatible",
        description="Preset profile name: phone_compatible, high_quality_h264",
    )
    uncertainty_notes: Optional[str] = Field(
        default=None,
        description="Any uncertainties, edge-cases, or manual review flags",
    )


def build_probe_summary(meta: MediaMetadata, deterministic: ClassificationResult) -> Dict[str, Any]:
    """Build a minimal, privacy-conscious technical metadata summary for Gemini."""
    v_streams = []
    for v in meta.video_streams:
        v_streams.append({
            "codec": v.codec_name,
            "profile": v.profile,
            "width": v.width,
            "height": v.height,
            "pix_fmt": v.pix_fmt,
            "fps": v.frame_rate,
            "is_hdr": v.is_hdr,
            "bitrate": v.bit_rate,
        })

    a_streams = []
    for a in meta.audio_streams:
        a_streams.append({
            "codec": a.codec_name,
            "channels": a.channels,
            "sample_rate": a.sample_rate,
            "layout": a.channel_layout,
            "language": a.language,
        })

    sub_streams = []
    for s in meta.subtitle_streams:
        sub_streams.append({
            "codec": s.codec_name,
            "language": s.language,
            "is_default": s.is_default,
        })

    return {
        "container": meta.container_format,
        "duration_sec": round(meta.duration, 2),
        "size_bytes": meta.size_bytes,
        "has_faststart": meta.has_faststart,
        "video_streams": v_streams,
        "audio_streams": a_streams,
        "subtitle_streams": sub_streams,
        "other_streams_count": meta.other_streams_count,
        "deterministic_status": deterministic.status,
        "deterministic_reasons": deterministic.reasons,
        "target_profile": deterministic.profile_name,
    }


def query_gemini_diagnostics(
    meta: MediaMetadata,
    deterministic: ClassificationResult
) -> Tuple[Optional[AIRecommendation], Optional[str]]:
    """Query Gemini for structured video diagnostics. Returns (recommendation, error_message)."""
    if not config.ai_enabled:
        return None, "AI analysis is disabled in configuration."

    if not config.has_gemini_key:
        return None, "GEMINI_API_KEY is not configured in .env."

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.gemini_api_key)
        summary = build_probe_summary(meta, deterministic)

        prompt = (
            "You are an expert video systems engineer inspecting media metadata for playback compatibility.\n"
            "Analyze the provided technical metadata and deterministic assessment below. Recommend the safest, most "
            "efficient processing action from: 'no_action', 'remux', 'transcode', 'manual_review'.\n\n"
            "Hard rules:\n"
            "1. If video/audio streams are already compatible with the target profile and only faststart (moov atom) "
            "or container wrapping is needed, choose 'remux' (do NOT transcode unnecessarily).\n"
            "2. If video codec, pixel format (e.g. 10-bit), HDR, or audio codec is incompatible, choose 'transcode'.\n"
            "3. If metadata indicates corruption or unreadable streams, choose 'manual_review'.\n"
            "4. Never output shell scripts, arbitrary ffmpeg commands, or make unverified claims.\n\n"
            f"Technical Metadata:\n{json.dumps(summary, indent=2)}"
        )

        response = client.models.generate_content(
            model=config.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AIRecommendation,
                temperature=0.2,
            ),
        )

        raw_text = response.text
        if not raw_text:
            return None, "Empty response received from Gemini API."

        # Parse & validate schema
        data = json.loads(raw_text)
        recommendation = AIRecommendation(**data)
        return recommendation, None

    except ValidationError as ve:
        logger.warning("Gemini response failed schema validation: %s", ve)
        return None, f"Response validation failed: {ve}"
    except Exception as e:
        logger.warning("Gemini API call failed: %s", e)
        return None, f"Gemini API request failed: {e}"


def validate_and_apply_ai_recommendation(
    ai_rec: Optional[AIRecommendation],
    deterministic: ClassificationResult
) -> ClassificationResult:
    """Validate AI recommendation against local deterministic constraints and produce final result."""
    if not ai_rec:
        # Seamless deterministic fallback
        return deterministic

    # If AI has low confidence or suggests manual review, prioritize caution
    if ai_rec.confidence < 0.6:
        logger.info("AI confidence low (%.2f). Using deterministic rule with AI reasoning.", ai_rec.confidence)
        deterministic.reasons.append(f"AI uncertain ({ai_rec.confidence * 100:.0f}% confidence): {ai_rec.reasoning}")
        return deterministic

    if ai_rec.action == "manual_review":
        return ClassificationResult(
            status="unknown",
            reasons=deterministic.reasons + [f"AI flagged for manual review: {ai_rec.reasoning}"],
            action="manual_review",
            needs_faststart_fix=deterministic.needs_faststart_fix,
            needs_video_transcode=deterministic.needs_video_transcode,
            needs_audio_transcode=deterministic.needs_audio_transcode,
            profile_name=deterministic.profile_name,
        )

    # Hard Safety Check 1: Corrupted or unreadable files can NEVER be marked 'no_action' or 'remux'
    if deterministic.status == "corrupt":
        logger.warning("Rejecting AI recommendation '%s' for corrupted file.", ai_rec.action)
        return deterministic

    # Hard Safety Check 2: If deterministic check determined transcoding is required (e.g. HEVC/VP9 or 10-bit color),
    # AI cannot downgrade it to 'no_action' or 'remux'
    if deterministic.needs_video_transcode or deterministic.needs_audio_transcode:
        if ai_rec.action in ("no_action", "remux"):
            logger.warning(
                "Rejecting AI downgrade to '%s'; deterministic incompatibility requires transcoding.",
                ai_rec.action
            )
            deterministic.reasons.append(f"AI suggested {ai_rec.action}, but overridden by required transcoding.")
            return deterministic

    # Hard Safety Check 3: If deterministic status is 'ok', AI cannot arbitrarily transcode without reason
    if deterministic.status == "ok" and ai_rec.action == "transcode":
        logger.warning("Rejecting unnecessary AI transcode recommendation for already compatible file.")
        deterministic.reasons.append("AI suggested transcode, but file already matches profile.")
        return deterministic

    # If valid and consistent, adopt AI guidance
    new_reasons = list(deterministic.reasons)
    new_reasons.append(f"AI ({ai_rec.confidence * 100:.0f}% confidence): {ai_rec.reasoning}")

    return ClassificationResult(
        status=deterministic.status,
        reasons=new_reasons,
        action=ai_rec.action,
        needs_faststart_fix=deterministic.needs_faststart_fix,
        needs_video_transcode=deterministic.needs_video_transcode,
        needs_audio_transcode=deterministic.needs_audio_transcode,
        profile_name=ai_rec.recommended_profile or deterministic.profile_name,
    )
