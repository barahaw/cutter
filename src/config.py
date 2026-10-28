"""Configuration management, path resolution, binary detection, and encoding profiles."""

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

from src.logging_config import logger


def get_base_dir() -> Path:
    """Return the base directory for the running application (frozen or script)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_binary(binary_name: str, env_var: str) -> Optional[str]:
    """Search for executable in:
    1. Specific environment variable (e.g. FFMPEG, FFPROBE).
    2. Next to the executable or script directory.
    3. 'assets/bin' directory relative to base_dir.
    4. Current working directory.
    5. System PATH via shutil.which.
    """
    env_val = os.environ.get(env_var, "").strip()
    if env_val and os.path.isfile(env_val):
        return str(Path(env_val).resolve())

    base_dir = get_base_dir()
    exe_name = f"{binary_name}.exe" if sys.platform == "win32" else binary_name

    # Check next to app
    candidate = base_dir / exe_name
    if candidate.is_file():
        return str(candidate.resolve())

    # Check assets/bin
    asset_candidate = base_dir / "assets" / "bin" / exe_name
    if asset_candidate.is_file():
        return str(asset_candidate.resolve())

    # Check cwd
    cwd_candidate = Path.cwd() / exe_name
    if cwd_candidate.is_file():
        return str(cwd_candidate.resolve())

    # Check PATH
    found = shutil.which(binary_name)
    if found:
        return str(Path(found).resolve())

    return None


@dataclass
class EncodingProfile:
    name: str
    description: str
    target_container: str = "mp4"
    video_codec: str = "libx264"
    allowed_vcodecs: List[str] = field(default_factory=lambda: ["h264"])
    allowed_profiles: List[str] = field(
        default_factory=lambda: ["Baseline", "Constrained Baseline", "Main", "High"]
    )
    allowed_pix_fmts: List[str] = field(default_factory=lambda: ["yuv420p"])
    audio_codec: str = "aac"
    allowed_acodecs: List[str] = field(default_factory=lambda: ["aac", "mp3"])
    crf: int = 22
    preset: str = "medium"
    audio_bitrate: str = "192k"
    max_width: Optional[int] = 1920
    max_height: Optional[int] = 1080
    max_fps: Optional[float] = 60.0
    require_faststart: bool = True


PROFILES: Dict[str, EncodingProfile] = {
    "phone_compatible": EncodingProfile(
        name="phone_compatible",
        description="Maximum compatibility for mobile phones (H.264 Baseline/Main/High, yuv420p, AAC, faststart)",
        target_container="mp4",
        video_codec="libx264",
        allowed_vcodecs=["h264"],
        allowed_profiles=["Baseline", "Constrained Baseline", "Main", "High"],
        allowed_pix_fmts=["yuv420p"],
        audio_codec="aac",
        allowed_acodecs=["aac"],
        crf=22,
        preset="medium",
        audio_bitrate="192k",
        max_width=1920,
        max_height=1080,
        max_fps=60.0,
        require_faststart=True,
    ),
    "high_quality_h264": EncodingProfile(
        name="high_quality_h264",
        description="High Quality H.264 (Preserves resolution, CRF 18, High profile, AAC)",
        target_container="mp4",
        video_codec="libx264",
        allowed_vcodecs=["h264"],
        allowed_profiles=["High", "Main"],
        allowed_pix_fmts=["yuv420p"],
        audio_codec="aac",
        allowed_acodecs=["aac", "alac", "flac"],
        crf=18,
        preset="slow",
        audio_bitrate="256k",
        max_width=None,
        max_height=None,
        max_fps=None,
        require_faststart=True,
    ),
}


class Config:
    """Manages application settings and external configuration."""

    def __init__(self):
        self.base_dir = get_base_dir()
        self.env_path = self.base_dir / ".env"
        self._load_environment()

        self.ffmpeg_path = resolve_binary("ffmpeg", "FFMPEG")
        self.ffprobe_path = resolve_binary("ffprobe", "FFPROBE")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        ai_enabled_raw = os.getenv("AI_ENABLED", "true").strip().lower()
        self.ai_enabled = ai_enabled_raw in ("1", "true", "yes", "on")

        if not self.ffmpeg_path:
            logger.warning("FFmpeg executable was not found on PATH or next to the application.")
        if not self.ffprobe_path:
            logger.warning("FFprobe executable was not found on PATH or next to the application.")

    def _load_environment(self):
        """Loads .env file relative to the executable/script directory or fallbacks."""
        candidates = [
            self.base_dir / ".env",
            self.base_dir / ".env.example",
            self.base_dir / ".env.txt",
            Path.cwd() / ".env",
            Path.cwd() / ".env.example",
            Path.cwd() / ".env.txt",
        ]
        loaded = False
        for p in candidates:
            if p.is_file():
                load_dotenv(dotenv_path=p, override=True)
                val = os.getenv("GEMINI_API_KEY", "").strip()
                if val and val != "your_api_key_here":
                    self.env_path = p
                    logger.info("Loaded configuration from %s", p)
                    loaded = True
                    break

        if not loaded:
            if (self.base_dir / ".env").is_file():
                load_dotenv(dotenv_path=self.base_dir / ".env", override=True)
                self.env_path = self.base_dir / ".env"
            else:
                logger.info("No active .env file found with GEMINI_API_KEY. Gemini AI will operate in fallback mode.")

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_api_key != "your_api_key_here")

    def save_api_key(self, api_key: str, model: str = "gemini-2.5-flash"):
        """Saves API key to the primary .env file next to the application."""
        target_env = self.base_dir / ".env"
        lines = [
            "# AI-Powered Video Fixer Configuration",
            f"GEMINI_API_KEY={api_key.strip()}",
            f"GEMINI_MODEL={model.strip()}",
            "AI_ENABLED=true\n",
        ]
        target_env.write_text("\n".join(lines), encoding="utf-8")
        self.reload()

    def reload(self):
        self._load_environment()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        ai_enabled_raw = os.getenv("AI_ENABLED", "true").strip().lower()
        self.ai_enabled = ai_enabled_raw in ("1", "true", "yes", "on")


# Singleton instance
config = Config()
