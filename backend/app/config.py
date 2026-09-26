"""Runtime settings, all from the environment (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _db_url(raw: str) -> str:
    """Accept the plain URL managed Postgres providers hand out (Neon,
    Supabase, RDS): 'postgres://' / 'postgresql://' -> the psycopg 3 driver."""
    raw = raw.strip()
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


@dataclass(frozen=True)
class Settings:
    database_url: str = _db_url(os.environ.get("DATABASE_URL", "postgresql+psycopg://nsq@localhost:5432/nsq"))
    # The Redis the app reads (in-server copy). Upstash is only touched by jobs.
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    upstash_url: str = os.environ.get("UPSTASH_URL", "")
    superadmin_email: str = os.environ.get("SUPERADMIN_EMAIL", "").strip().lower()
    superadmin_password: str = os.environ.get("SUPERADMIN_PASSWORD", "")
    session_ttl_hours: int = int(os.environ.get("SESSION_TTL_HOURS", "12"))
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    app_base_url: str = os.environ.get("APP_BASE_URL", "http://localhost")
    core_dir: Path = Path(os.environ.get("CORE_DIR", str(_REPO / "core")))
    loader_dir: Path = Path(os.environ.get("LOADER_DIR", str(_REPO / "redis-loader")))
    data_dir: Path = Path(os.environ.get("DATA_DIR", str(_REPO / "data")))
    snapshot_path: Path = Path(os.environ.get("NSQ_SNAPSHOT", str(_REPO / "data" / "nsq_snapshot.json.gz")))
    frame_ttl_s: float = float(os.environ.get("FRAME_TTL_S", "300"))
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    ])


settings = Settings()

SESSION_COOKIE = "nsq_session"
CLIENT_HEADER = "x-nsq-client"  # required on every mutating request (CSRF guard)
MIN_PASSWORD_LENGTH = 8
