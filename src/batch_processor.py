"""Batch processing orchestrator coordinating inspection, AI diagnosis, repair/encoding, and verification."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from src.ai_analyzer import query_gemini_diagnostics, validate_and_apply_ai_recommendation
from src.config import EncodingProfile, PROFILES
from src.logging_config import logger
from src.media_analyzer import ClassificationResult, analyze_media
from src.media_probe import MediaMetadata, probe_media
from src.processing import remux_file, transcode_file
from src.verification import VerificationResult, verify_output


@dataclass
class JobResult:
    source_path: str
    destination_path: Optional[str] = None
    status: str = "pending"  # "completed", "skipped", "failed", "cancelled"
    action_taken: str = "none"  # "none", "remux", "transcode"
    meta: Optional[MediaMetadata] = None
    classification: Optional[ClassificationResult] = None
    verification: Optional[VerificationResult] = None
    error_message: Optional[str] = None


class BatchProcessor:
    """Orchestrates end-to-end processing pipeline for video files."""

    def __init__(
        self,
        profile: Optional[EncodingProfile] = None,
        out_dir: Optional[str] = None,
        suffix: str = "_fixed",
        use_ai: bool = True,
        force_mode: Optional[str] = None,  # None (auto), "remux_only", "transcode_only"
    ):
        self.profile = profile or PROFILES["phone_compatible"]
        self.out_dir = Path(out_dir).resolve() if out_dir else None
        self.suffix = suffix
        self.use_ai = use_ai
        self.force_mode = force_mode
        self._cancel_flag = False
        self._current_process = None

    def cancel(self):
        self._cancel_flag = True
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.kill()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel_flag

    def calculate_destination(self, src: str) -> Path:
        src_path = Path(src).resolve()
        parent = self.out_dir if self.out_dir else src_path.parent
        target_ext = f".{self.profile.target_container}"
        dst_name = f"{src_path.stem}{self.suffix}{target_ext}"
        return parent / dst_name

    def process_file(
        self,
        src: str,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> JobResult:
        """Process a single file through probe, classification, AI advice, processing, and verification."""
        if self._cancel_flag:
            return JobResult(source_path=src, status="cancelled", error_message="Job was cancelled.")

        job = JobResult(source_path=src)

        # 1. Inspection
        try:
            meta = probe_media(src)
            job.meta = meta
        except Exception as e:
            job.status = "failed"
            job.error_message = f"Failed to probe file: {e}"
            logger.error("Probe error for %s: %s", src, e)
            return job

        # 2. Deterministic analysis
        classification = analyze_media(meta, profile=self.profile)

        # 3. AI diagnosis if enabled
        if self.use_ai and not self._cancel_flag:
            try:
                ai_rec, ai_err = query_gemini_diagnostics(meta, classification)
                if ai_rec:
                    classification = validate_and_apply_ai_recommendation(ai_rec, classification)
                elif ai_err:
                    logger.debug("AI advice not applied for %s: %s", src, ai_err)
            except Exception as e:
                logger.warning("AI query exception for %s: %s", src, e)

        job.classification = classification

        # Determine target action
        action = classification.action
        if self.force_mode == "remux_only":
            action = "remux"
        elif self.force_mode == "transcode_only":
            action = "transcode"

        # 4. Handle No Action (already compatible)
        if action == "no_action" or classification.status == "ok":
            job.status = "completed"
            job.action_taken = "none"
            logger.info("File '%s' is already compatible. No action needed.", os.path.basename(src))
            return job

        # Handle corrupt or unknown files
        if classification.status in ("corrupt", "unknown") and action == "manual_review":
            job.status = "failed"
            job.error_message = f"Manual review required: {classification.summary()}"
            return job

        # 5. Prepare Destination
        dst_path = self.calculate_destination(src)
        job.destination_path = str(dst_path)

        def register_process(proc):
            self._current_process = proc

        # 6. Execute Remux or Transcode to Temporary File
        temp_file: Optional[Path] = None
        try:
            if action == "remux":
                job.action_taken = "remux"
                logger.info("Remuxing '%s' to '%s'...", os.path.basename(src), dst_path.name)
                temp_file = remux_file(
                    src=src,
                    dst=str(dst_path),
                    meta=meta,
                    on_progress=on_progress,
                    cancel=self.is_cancelled,
                    on_process=register_process,
                )
            elif action == "transcode":
                job.action_taken = "transcode"
                logger.info("Transcoding '%s' to '%s'...", os.path.basename(src), dst_path.name)
                temp_file = transcode_file(
                    src=src,
                    dst=str(dst_path),
                    meta=meta,
                    profile=self.profile,
                    on_progress=on_progress,
                    cancel=self.is_cancelled,
                    on_process=register_process,
                )
            else:
                job.status = "skipped"
                job.error_message = f"Unsupported action: {action}"
                return job

        except Exception as e:
            job.status = "failed"
            job.error_message = f"Processing error: {e}"
            logger.error("Processing failed for %s: %s", src, e)
            if temp_file and temp_file.exists():
                temp_file.unlink(missing_ok=True)
            return job

        if self._cancel_flag:
            if temp_file and temp_file.exists():
                temp_file.unlink(missing_ok=True)
            job.status = "cancelled"
            job.error_message = "Cancelled by user"
            return job

        # 7. Verification of Temporary Output
        try:
            v_res = verify_output(
                src_meta=meta,
                out_path=str(temp_file),
                profile=self.profile,
            )
            job.verification = v_res

            if v_res.is_valid:
                # Atomic replacement of temporary file into destination
                temp_file.replace(dst_path)
                job.status = "completed"
                if on_progress:
                    on_progress(1.0)
                logger.info("Successfully verified and saved output: %s", dst_path)
            else:
                job.status = "failed"
                job.error_message = v_res.summary()
                logger.warning("Verification failed for %s: %s", dst_path, job.error_message)
                if temp_file.exists():
                    temp_file.unlink(missing_ok=True)

        except Exception as e:
            job.status = "failed"
            job.error_message = f"Verification error: {e}"
            if temp_file and temp_file.exists():
                temp_file.unlink(missing_ok=True)

        return job
