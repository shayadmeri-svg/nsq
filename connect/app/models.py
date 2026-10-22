"""Connect's records: plants, their equipment (and how each is reached), products with their routes through that
equipment, edge agents, the jobs agents run for the setup wizard, readings, batches and alarms."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(d: Optional[datetime]) -> Optional[str]:
    """ISO time in UTC; a database that drops the zone (SQLite) gives naive values, which are UTC here."""
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


class Plant(Base):
    __tablename__ = "cx_plants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_slug: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(160), default="")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Equipment(Base):
    """A machine: its type (catalog template), where it sits on the line, how it is reached (protocol + config),
    which of its tags is which signal, and where its batch number and product come from."""
    __tablename__ = "cx_equipment"
    __table_args__ = (UniqueConstraint("plant_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("cx_plants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    type: Mapped[str] = mapped_column(String(40))
    line: Mapped[str] = mapped_column(String(60), default="Line 1")
    position: Mapped[int] = mapped_column(Integer, default=0)
    make: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    protocol: Mapped[str] = mapped_column(String(30), default="opcua")
    connection: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tag_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    batch_tag: Mapped[str] = mapped_column(String(200), default="")
    product_tag: Mapped[str] = mapped_column(String(200), default="")
    agent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profile_id: Mapped[str] = mapped_column(String(80), default="")


class Product(Base):
    """A product made on the plant and its route: [{equipment_id, params: {signal: {ideal, lo, hi, check, source}}}].
    Machines shared between products appear in several routes; a product-specific step in one."""
    __tablename__ = "cx_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("cx_plants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    molecule_key: Mapped[str] = mapped_column(String(160), default="")
    dosage_form: Mapped[str] = mapped_column(String(40), default="tablet")
    codes: Mapped[list[str]] = mapped_column(JSON, default=list)  # what the machines report as the product
    color: Mapped[str] = mapped_column(String(12), default="#06a7c4")
    route: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Agent(Base):
    __tablename__ = "cx_agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("cx_plants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hint: Mapped[str] = mapped_column(String(16), default="")
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Job(Base):
    """Work the cloud asks an edge agent to do (it cannot reach the plant): browse a machine's tags, test-read them."""
    __tablename__ = "cx_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(Integer, index=True)
    equipment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Reading(Base):
    __tablename__ = "cx_readings"
    __table_args__ = (Index("ix_cx_readings_eq_ts", "equipment_id", "ts"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    plant_id: Mapped[int] = mapped_column(Integer, index=True)
    equipment_id: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signal: Mapped[str] = mapped_column(String(60))
    value: Mapped[float] = mapped_column(Float)
    batch: Mapped[str] = mapped_column(String(80), default="")


class Batch(Base):
    """A batch as it moves through the plant: per equipment, when it was first and last seen there."""
    __tablename__ = "cx_batches"
    __table_args__ = (UniqueConstraint("plant_id", "batch_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(Integer, index=True)
    batch_no: Mapped[str] = mapped_column(String(80))
    product_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    product_label: Mapped[str] = mapped_column(String(160), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    steps: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {equipment_id: {first, last, end: {signal: value}}}


class Alarm(Base):
    __tablename__ = "cx_alarms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(Integer, index=True)
    equipment_id: Mapped[int] = mapped_column(Integer)
    batch: Mapped[str] = mapped_column(String(80), default="")
    product_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signal: Mapped[str] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(10))  # alarm (outside the acceptable range) | warn (outer 20 % of it)
    message: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    acked_by: Mapped[str] = mapped_column(String(254), default="")
