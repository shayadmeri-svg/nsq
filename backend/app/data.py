"""Access to the NSQ dataset and CDMO intelligence held in Redis.

One in-process cache for the enriched frame (the expensive object) and the
CDMO seed maps, with explicit invalidation that jobs call after a refresh.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import redis

from .config import settings

# core/ modules read these from the environment.
os.environ.setdefault("REDIS_URL", settings.redis_url)
os.environ.setdefault("NSQ_SNAPSHOT", str(settings.snapshot_path))

import data_loader  # noqa: E402
import intelligence_store as store  # noqa: E402
import nsq_redis  # noqa: E402

_lock = threading.Lock()
_frame: Optional[tuple[float, pd.DataFrame, str]] = None  # (expires, df, source)
_cdmo: Optional[tuple[float, dict[str, Any]]] = None


def redis_client() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)


def _build_frame() -> tuple[pd.DataFrame, str]:
    df = data_loader.load_enriched_frame()
    if df is not None and not df.empty:
        return df, "redis:precomputed"
    df = data_loader._load_and_preprocess()
    return df, "computed"


def frame() -> pd.DataFrame:
    """The enriched NSQ frame (all alerts), cached for FRAME_TTL_S."""
    global _frame
    now = time.monotonic()
    cached = _frame
    if cached is not None and now < cached[0]:
        return cached[1]
    with _lock:
        if _frame is None or time.monotonic() >= _frame[0]:
            df, source = _build_frame()
            if "Parsed_Date" in df.columns:
                df["Parsed_Date"] = pd.to_datetime(df["Parsed_Date"], errors="coerce")
            _frame = (time.monotonic() + settings.frame_ttl_s, df, source)
        return _frame[1]


def frame_source() -> str:
    return _frame[2] if _frame else "not loaded"


def cdmo() -> dict[str, Any]:
    """Patents, regulatory passports, demand profiles and plants, cached."""
    global _cdmo
    now = time.monotonic()
    if _cdmo is not None and now < _cdmo[0]:
        return _cdmo[1]
    r = redis_client()
    maps = {
        "patents": store.load_all_patents(r),
        "regulatory": store.load_all_regulatory(r),
        "demand": store.load_all_demand(r),
        "plants": store.load_all_plant_assets(r),
    }
    _cdmo = (now + 120.0, maps)
    return maps


def invalidate() -> None:
    global _frame, _cdmo
    with _lock:
        _frame = None
        _cdmo = None


def org_frame(ontology_keys: list[str]) -> pd.DataFrame:
    df = frame()
    if df.empty or not ontology_keys or "Mfg_Ontology_Key" not in df.columns:
        return df.iloc[0:0]
    return df[df["Mfg_Ontology_Key"].isin(ontology_keys)]


def data_status() -> dict[str, Any]:
    """Freshness of every tier: local Redis, precomputed frame, snapshot file."""
    out: dict[str, Any] = {"checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        r = redis_client()
        info = r.info("memory")
        out["redis"] = {
            "ok": True,
            "records": r.scard("nsq:records"),
            "meta": r.hgetall("nsq:meta"),
            "frame": r.hgetall("nsq:frame:enriched:meta"),
            "used_memory_mb": round(info.get("used_memory", 0) / 1e6, 1),
            "maxmemory_mb": round((info.get("maxmemory") or 0) / 1e6, 1),
            "cdmo": {
                fam: sum(1 for _ in r.scan_iter(match=f"cdmo:{fam}:*", count=500))
                for fam in ("patent", "regulatory", "demand", "plant", "portfolio")
            },
        }
    except Exception as exc:  # pragma: no cover - depends on infra
        out["redis"] = {"ok": False, "error": str(exc)}

    snap = settings.snapshot_path
    if snap.exists():
        st = snap.stat()
        entry: dict[str, Any] = {
            "path": str(snap), "bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        }
        try:
            with gzip.open(snap, "rt", encoding="utf-8") as fh:
                head = json.load(fh)
            entry["generated_at"] = head.get("generated_at")
            entry["records"] = len((head.get("sections") or {}).get("records") or {})
        except Exception:
            pass
        out["snapshot"] = entry
    else:
        out["snapshot"] = None

    out["frame_source"] = frame_source()
    out["upstash_configured"] = bool(settings.upstash_url)
    return out
