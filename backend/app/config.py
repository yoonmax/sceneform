"""Runtime configuration (environment variables prefixed ``SCENEFORM_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default, cast=str):
    raw = os.environ.get(f"SCENEFORM_{name}")
    if raw is None:
        return default
    if cast is bool:
        return raw.lower() in ("1", "true", "yes", "on")
    return cast(raw)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", Path(__file__).resolve().parents[1] / "var")))
    # Upload limits
    max_upload_bytes: int = field(default_factory=lambda: _env("MAX_UPLOAD_MB", 1024, int) * 1024 * 1024)
    max_image_bytes: int = 40 * 1024 * 1024
    max_images: int = field(default_factory=lambda: _env("MAX_IMAGES", 300, int))
    max_video_seconds: float = field(default_factory=lambda: _env("MAX_VIDEO_SECONDS", 300.0, float))
    max_image_pixels: int = 100_000_000
    # Jobs
    max_concurrent_jobs: int = field(default_factory=lambda: _env("MAX_CONCURRENT_JOBS", 1, int))
    max_queued_jobs_per_owner: int = 3
    job_timeout_seconds: int = field(default_factory=lambda: _env("JOB_TIMEOUT", 3 * 3600, int))
    # Retention
    retention_hours: float = field(default_factory=lambda: _env("RETENTION_HOURS", 72.0, float))
    # Rate limiting (requests per minute per owner token)
    rate_limit_per_minute: int = 240
    # CORS
    cors_origins: list[str] = field(
        default_factory=lambda: [o for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]
    )
    depth_model: str = field(default_factory=lambda: _env("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sceneform.sqlite3"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


settings = Settings()
