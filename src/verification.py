"""Multi-stage verification of processed media outputs."""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from src.config import EncodingProfile, PROFILES, config
from src.logging_config import logger
from src.media_probe import MediaMetadata, has_faststart, probe_media

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class VerificationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_diff: float = 0.0
    faststart_ok: bool = False
    decode_test_passed: bool = False

    def summary(self) -> str:
        if self.is_valid:
            warn = f" ({len(self.warnings)} warnings)" if self.warnings else ""
            return f"Verified successfully{warn}"
        return f"Verification FAILED: {'; '.join(self.errors)}"


def run_decode_test(path: str, max_duration_sec: float = 10.0) -> Tuple[bool, Optional[str]]:
    """Runs a null-mux decode test on the beginning of the file to catch corruption."""
    ffmpeg = config.ffmpeg_path
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return False, "FFmpeg binary unavailable for decode test"

    cmd = [
        ffmpeg,
        "-v", "error",
        "-nostdin",
        "-t", str(max_duration_sec),
        "-i", path,
        "-f", "null",
        "-",
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=25,
        )
        if res.returncode != 0:
            err = res.stderr.strip() or "Decode test returned non-zero code"
            return False, err
        return True, None
    except subprocess.TimeoutExpired:
        return False, "Decode test timed out"
    except Exception as e:
        return False, f"Decode test error: {e}"


def verify_output(
    src_meta: MediaMetadata,
    out_path: str,
    profile: Optional[EncodingProfile] = None,
    tolerance: float = 1.5,
    run_decode: bool = True,
) -> VerificationResult:
    """Rigorous verification of processed output against source and profile expectations."""
    target = profile or PROFILES["phone_compatible"]
    errors: List[str] = []
    warnings: List[str] = []

    out = Path(out_path)
    # 1. Existence and non-empty check
    if not out.is_file():
        return VerificationResult(is_valid=False, errors=["Output file does not exist on disk."])

    out_size = out.stat().st_size
    if out_size < 1024:
        return VerificationResult(
            is_valid=False,
            errors=[f"Output file is suspiciously small or empty ({out_size} bytes)."]
        )

    # 2. Fast-start check for MP4
    fs_ok = False
    if target.require_faststart:
        fs = has_faststart(str(out))
        if fs is not True:
            errors.append("Faststart check failed: 'moov' atom is not positioned before 'mdat'.")
        else:
            fs_ok = True

    # 3. Probe output metadata
    try:
        out_meta = probe_media(str(out))
    except Exception as e:
        return VerificationResult(
            is_valid=False,
            errors=[f"Failed to probe output file: {e}"],
            faststart_ok=fs_ok,
        )

    if out_meta.probe_error:
        return VerificationResult(
            is_valid=False,
            errors=[f"Output probe error: {out_meta.probe_error}"],
            faststart_ok=fs_ok,
        )

    # 4. Compare duration
    duration_diff = abs(src_meta.duration - out_meta.duration)
    if src_meta.duration > 0 and out_meta.duration > 0:
        if duration_diff > tolerance:
            errors.append(
                f"Duration mismatch: source {src_meta.duration:.2f}s vs output {out_meta.duration:.2f}s "
                f"(difference {duration_diff:.2f}s exceeds {tolerance}s tolerance)."
            )
    elif src_meta.duration > 0 and out_meta.duration == 0:
        errors.append("Output file has 0 duration.")

    # 5. Validate Video Stream
    if not out_meta.video_streams:
        errors.append("Output file contains no video streams.")
    else:
        v_out = out_meta.video_streams[0]
        if v_out.codec_name.lower() not in [c.lower() for c in target.allowed_vcodecs]:
            errors.append(f"Output video codec '{v_out.codec_name}' does not match target {target.allowed_vcodecs}.")
        if v_out.pix_fmt and v_out.pix_fmt.lower() not in [p.lower() for p in target.allowed_pix_fmts]:
            errors.append(f"Output pixel format '{v_out.pix_fmt}' does not match target {target.allowed_pix_fmts}.")

    # 6. Validate Audio Stream Presence
    if src_meta.has_audio and not out_meta.has_audio:
        errors.append("Source file had audio, but output file has no audio streams.")

    # 7. Decode integrity test
    decode_passed = False
    if run_decode:
        test_dur = min(src_meta.duration, 10.0) if src_meta.duration > 0 else 10.0
        passed, dec_err = run_decode_test(str(out), max_duration_sec=test_dur)
        decode_passed = passed
        if not passed:
            errors.append(f"Output decode test failed: {dec_err}")
    else:
        decode_passed = True

    is_valid = len(errors) == 0
    return VerificationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        duration_diff=duration_diff,
        faststart_ok=fs_ok,
        decode_test_passed=decode_passed,
    )
