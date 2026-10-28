"""Deterministic classification of media files based on target profiles."""

from dataclasses import dataclass, field
from typing import List, Optional

from src.config import EncodingProfile, PROFILES
from src.media_probe import MediaMetadata


@dataclass
class ClassificationResult:
    status: str  # "ok", "needs-remux", "needs-transcode", "corrupt", "unknown"
    reasons: List[str] = field(default_factory=list)
    action: str = "no_action"  # "no_action", "remux", "transcode", "manual_review"
    needs_faststart_fix: bool = False
    needs_video_transcode: bool = False
    needs_audio_transcode: bool = False
    profile_name: str = "phone_compatible"

    def summary(self) -> str:
        if not self.reasons:
            return "File matches compatibility target."
        return "; ".join(self.reasons)


def analyze_media(
    meta: MediaMetadata,
    profile: Optional[EncodingProfile] = None
) -> ClassificationResult:
    """Deterministically analyze a probed media file against an encoding profile."""
    target = profile or PROFILES["phone_compatible"]

    if meta.probe_error or meta.size_bytes == 0:
        err = meta.probe_error or "Empty file (0 bytes)"
        return ClassificationResult(
            status="corrupt",
            reasons=[f"File inspection failed: {err}"],
            action="manual_review",
            profile_name=target.name,
        )

    if not meta.video_streams:
        return ClassificationResult(
            status="unknown",
            reasons=["No video stream found in container"],
            action="manual_review",
            profile_name=target.name,
        )

    v = meta.video_streams[0]
    reasons: List[str] = []
    needs_v_transcode = False
    needs_a_transcode = False
    needs_remux = False

    # 1. Video Codec Check
    if v.codec_name.lower() not in [c.lower() for c in target.allowed_vcodecs]:
        needs_v_transcode = True
        reasons.append(
            f"Video codec '{v.codec_name}' incompatible (requires {', '.join(target.allowed_vcodecs)})"
        )

    # 2. Pixel format check (e.g. 10-bit vs 8-bit yuv420p)
    if v.pix_fmt and v.pix_fmt.lower() not in [p.lower() for p in target.allowed_pix_fmts]:
        needs_v_transcode = True
        reasons.append(
            f"Pixel format '{v.pix_fmt}' incompatible (requires {', '.join(target.allowed_pix_fmts)})"
        )

    # 3. Profile check
    if v.profile and target.allowed_profiles:
        profile_root = v.profile.split()[0]
        if not any(allowed.lower() in v.profile.lower() for allowed in target.allowed_profiles):
            needs_v_transcode = True
            reasons.append(
                f"Video profile '{v.profile}' not in allowed set ({', '.join(target.allowed_profiles)})"
            )

    # 4. HDR check
    if v.is_hdr:
        needs_v_transcode = True
        reasons.append("HDR color transfer detected; tone mapping/transcoding needed for standard phone playback")

    # 5. Dimensions check
    if target.max_width and v.width > target.max_width:
        needs_v_transcode = True
        reasons.append(f"Width {v.width}px exceeds max allowed {target.max_width}px")
    if target.max_height and v.height > target.max_height:
        needs_v_transcode = True
        reasons.append(f"Height {v.height}px exceeds max allowed {target.max_height}px")

    # 6. Audio streams check
    for a in meta.audio_streams:
        if a.codec_name.lower() not in [c.lower() for c in target.allowed_acodecs]:
            needs_a_transcode = True
            reasons.append(f"Audio codec '{a.codec_name}' not in allowed list ({', '.join(target.allowed_acodecs)})")
            break

    # 7. Faststart and Container Check
    container_is_target = target.target_container in meta.container_format.lower()
    needs_fs = False
    if target.require_faststart:
        if meta.has_faststart is False:
            needs_fs = True
            reasons.append("MP4 index (moov atom) is at end of file; faststart required")
        elif meta.has_faststart is None and not container_is_target:
            needs_remux = True
            reasons.append(f"Container format '{meta.container_format}' needs remuxing to {target.target_container}")

    # Determine status & action
    if needs_v_transcode or needs_a_transcode:
        return ClassificationResult(
            status="needs-transcode",
            reasons=reasons,
            action="transcode",
            needs_faststart_fix=needs_fs,
            needs_video_transcode=needs_v_transcode,
            needs_audio_transcode=needs_a_transcode,
            profile_name=target.name,
        )

    if needs_fs or needs_remux:
        return ClassificationResult(
            status="needs-remux",
            reasons=reasons,
            action="remux",
            needs_faststart_fix=needs_fs,
            needs_video_transcode=False,
            needs_audio_transcode=False,
            profile_name=target.name,
        )

    return ClassificationResult(
        status="ok",
        reasons=[],
        action="no_action",
        needs_faststart_fix=False,
        needs_video_transcode=False,
        needs_audio_transcode=False,
        profile_name=target.name,
    )
