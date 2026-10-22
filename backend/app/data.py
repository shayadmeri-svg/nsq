"""Access to the NSQ dataset and CDMO intelligence held in Redis.

One in-process cache for the enriched frame (the expensive object) and the
CDMO seed maps, with explicit invalidation that jobs call after a refresh.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import redis

from .config import settings

log = logging.getLogger(__name__)

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


# CDSCO lists a batch "declared spurious" under the manufacturer printed on its
# label. Often that company has told the regulator it never made the batch (a
# counterfeit); sometimes the label maker is the culprit (e.g. an Ayurvedic
# product spiked with an allopathic drug). Either way attribution is
# unconfirmed, so these rows never count in company rankings and are flagged.
SPURIOUS_RE = re.compile(r"spurious|not\s+been\s+manufactured\s+by|not\s+manufactured\s+by|disown", re.I)


def mark_spurious(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "_spurious" in df.columns:
        return df
    txt = df.get("NSQ Result", pd.Series("", index=df.index)).astype(str) + " " + \
        df.get("Manufactured By", pd.Series("", index=df.index)).astype(str)
    df["_spurious"] = txt.str.contains(SPURIOUS_RE)
    return df


def attributable(df: pd.DataFrame) -> pd.DataFrame:
    """Alerts that can fairly be attributed to the named manufacturer."""
    return df[~df["_spurious"]] if "_spurious" in df.columns else df


def _build_frame() -> tuple[pd.DataFrame, str]:
    df = data_loader.load_enriched_frame()
    if df is not None and not df.empty:
        return df, "redis:precomputed"
    df = data_loader._load_and_preprocess()
    return df, "computed"


def _fresh_frame() -> tuple[float, pd.DataFrame, str]:
    df, source = _build_frame()
    if "Parsed_Date" in df.columns:
        df["Parsed_Date"] = pd.to_datetime(df["Parsed_Date"], errors="coerce")
    return time.monotonic() + settings.frame_ttl_s, mark_spurious(df), source


def frame() -> pd.DataFrame:
    """The enriched NSQ frame (all alerts). Only the first load waits for the build; once the copy is FRAME_TTL_S
    old it is rebuilt in the background while requests keep reading it, so no request stalls on a refresh."""
    global _frame
    cached = _frame
    if cached is not None:
        if time.monotonic() >= cached[0]:
            _refresh_in_background()
        return cached[1]
    with _lock:
        if _frame is None:
            _frame = _fresh_frame()
        return _frame[1]


_refreshing = threading.Lock()
_generation = 0  # bumped by invalidate(), so a refresh started before it cannot put older data back


def _refresh_in_background() -> None:
    if not _refreshing.acquire(blocking=False):
        return  # one refresh at a time
    gen = _generation

    def work() -> None:
        global _frame
        try:
            fresh = _fresh_frame()
            with _lock:
                if gen == _generation:
                    _frame = fresh
        except Exception as exc:  # keep serving the copy we have
            log.warning("NSQ frame refresh failed: %s", exc)
        finally:
            _refreshing.release()

    threading.Thread(target=work, name="nsq-frame-refresh", daemon=True).start()


def warm() -> None:
    """Build the frame off the request path at start-up, so the first visitor does not wait for it."""
    threading.Thread(target=frame, name="nsq-frame-warm", daemon=True).start()


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
    try:  # profiles linked to a registry plant take their certifications from the official records
        from . import plants as registry_plants
        maps["plants"] = {k: registry_plants.apply_official(v) for k, v in maps["plants"].items()}
    except Exception as exc:  # the registry is optional (no source files on a fresh install)
        log.warning("plant profiles not linked to the registry: %s", exc)
    _cdmo = (now + 120.0, maps)
    return maps


def invalidate() -> None:
    global _frame, _cdmo, _generation
    with _lock:
        _generation += 1
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
