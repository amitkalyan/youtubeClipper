"""Hardware-safe defaults for an 8 GB, CPU-only Windows machine."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.errors import ClipperError

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_WHISPER_MODELS = {"tiny", "tiny.en", "base", "base.en", "small", "small.en"}
ALLOWED_COMPUTE_TYPES = {"int8", "int8_float32", "float32"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(project_root() / ".env"),),
        extra="ignore",
    )

    app_name: str = "Clipper"
    data_dir: Path = Field(default_factory=lambda: project_root() / "data")
    clipper_model_cache: Path | None = None
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_threads: int = 4
    whisper_vad_filter: bool = True
    max_concurrent_jobs: int = 1
    max_queued_jobs: int = 4
    max_upload_bytes: int = 4 * 1024 * 1024 * 1024
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_num_ctx: int = 4096
    ollama_timeout_seconds: int = 300
    output_path: Path | None = Field(default=None, validation_alias="OUTPUT_DIR")

    def resolved_model_cache(self) -> Path:
        if self.clipper_model_cache is not None:
            return self.clipper_model_cache
        return self.data_dir / "models"

    def output_dir(self) -> Path:
        if self.output_path is not None:
            return self.output_path
        return project_root() / "output"

    def effective_threads(self) -> int:
        cpu = os.cpu_count() or 1
        return max(1, min(int(self.whisper_threads), cpu))

    def assert_hardware_profile(self) -> None:
        if self.whisper_device.strip().lower() != "cpu":
            raise ClipperError(
                "Whisper device must be cpu. This application is built for a machine without a GPU."
            )
        compute = self.whisper_compute_type.strip().lower()
        if compute not in ALLOWED_COMPUTE_TYPES:
            raise ClipperError("Whisper compute type must be int8, int8_float32, or float32.")
        model = self.whisper_model.strip().lower()
        if model not in ALLOWED_WHISPER_MODELS and os.environ.get("CLIPPER_ALLOW_LARGE_MODELS") != "1":
            raise ClipperError(
                f"Whisper model '{self.whisper_model}' is too heavy for an 8 GB CPU-only machine. "
                "Use base or small. Set CLIPPER_ALLOW_LARGE_MODELS=1 only after measuring memory."
            )
        if int(self.max_concurrent_jobs) != 1:
            raise ClipperError("MAX_CONCURRENT_JOBS must stay 1 so only one heavy job runs.")
        if int(self.whisper_threads) < 1:
            raise ClipperError("WHISPER_THREADS must be at least 1.")
        if int(self.max_queued_jobs) < 0:
            raise ClipperError("MAX_QUEUED_JOBS cannot be negative.")

    def hardware_profile_issue(self) -> str | None:
        try:
            self.assert_hardware_profile()
        except ClipperError as exc:
            return str(exc)
        return None

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.data_dir / "projects",
            self.data_dir / "logs",
            self.resolved_model_cache() / "whisper",
            self.resolved_model_cache() / "hf",
            self.output_dir(),
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
