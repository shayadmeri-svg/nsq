"""Relational data: organisations, users, sessions, invites, audit, jobs, plants.

The NSQ dataset and CDMO seeds stay in Redis; Postgres holds everything
people create or that must survive a Redis rebuild.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLES = ("super_admin", "admin", "org_admin", "member")
PLATFORM_ROLES = ("super_admin", "admin")
PERSONAS = ("QA", "Regulatory", "Executive")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(80), default="India")
    # NSQ manufacturer identities (Mfg_Ontology_Key values) this org answers for.
    ontology_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    # cdmo:plant:* asset ids this org operates.
    plant_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="org")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")
    org_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orgs.id", ondelete="SET NULL"), nullable=True)
    persona: Mapped[str] = mapped_column(String(20), default="QA")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped[Optional[Org]] = relationship(back_populates="users")

    @property
    def is_platform(self) -> bool:
        return self.role in PLATFORM_ROLES


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(token)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="member")
    org_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str] = mapped_column(String(254), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_key: Mapped[str] = mapped_column(String(60), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|succeeded|failed
    started_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_by_email: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    log: Mapped[str] = mapped_column(Text, default="")


class Plant(Base):
    """Backup of user-created plant profiles (the live copy is cdmo:plant:* in Redis)."""

    __tablename__ = "plants"

    asset_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    org_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orgs.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=func.now())
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PipelineSchedule(Base):
    """When a job runs on its own (Admin → Pipelines). Times are in SCHEDULE_TZ (default Asia/Kolkata)."""

    __tablename__ = "pipeline_schedules"

    job_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    frequency: Mapped[str] = mapped_column(String(10), default="daily")  # daily | weekly | monthly
    hour: Mapped[int] = mapped_column(Integer, default=2)
    minute: Mapped[int] = mapped_column(Integer, default=30)
    weekday: Mapped[int] = mapped_column(Integer, default=0)  # 0 = Monday (weekly)
    day: Mapped[int] = mapped_column(Integer, default=1)  # day of month (monthly)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[str] = mapped_column(String(254), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=func.now())


class WatchMolecule(Base):
    """Admin additions to (or exclusions from) the auto-built molecule universe."""

    __tablename__ = "watch_molecules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(160), index=True, default="")
    exclude: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    added_by: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MoleculeEntry(Base):
    """Values typed into the molecule form. They win over the curated seed and
    the public sources when the universe is built (the source value is kept
    alongside for comparison). `added` = the molecule was created in the app
    (always tracked); otherwise these are edits to a seeded / auto molecule."""

    __tablename__ = "molecule_entries"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    added: Mapped[bool] = mapped_column(Boolean, default=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(254), default="")
    updated_by: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=func.now())
