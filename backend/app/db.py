"""SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _connect_args(url: str) -> dict:
    # Connection poolers (Neon "-pooler" hosts, PgBouncer, Supabase :6543) run in
    # transaction mode: server-side prepared statements must be off.
    if "pooler" in url or ":6543" in url or "pgbouncer" in url:
        return {"prepare_threshold": None}
    return {}


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300, future=True,
                       connect_args=_connect_args(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
