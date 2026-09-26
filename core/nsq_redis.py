"""Load NSQ alert records from Redis into a pandas DataFrame.

Reads the keys written by redis-loader/load_nsq_redis.py:
  nsq:records            -> SET of record ids
  nsq:record:<id>        -> HASH of one row (CDSCO publicNsqDrugTable field names)

Field names coming out of Redis use the CDSCO API's own prefixes
(str_product_name, dt_reporting_month_year, ...). This module renames
them to the column names the existing analytics/simulator code already
expects (the same names the original CSV export used), so downstream
logic in both apps is unchanged.

Redis (the prod cluster) is the source of truth. Between Redis and the
CSV sits a second tier: a local snapshot file (NSQ_SNAPSHOT, default
'data/nsq_snapshot.json.gz') written by redis-loader/dump_snapshot.py.
When Redis fails — e.g. the Upstash monthly command quota is exhausted,
which raises redis.RedisError on every command — the snapshot serves the
same records, predictions, ontologies and geojson Redis holds, so
production shows data as of the last refresh instead of an empty
dashboard.

If Redis is unreachable or returns an empty dataset and no snapshot
exists, load_dataframe() falls back to reading the CSV specified by
NSQ_CSV (default the cumulative CDSCO export named in the justfile's CSV
variable) directly via pandas. That file is gitignored (``data/*.csv``)
and is NOT copied into the service images, so the CSV tier only ever
fires host-side; in a container an unreachable Redis surfaces as an
empty frame. The simulator doesn't use the CSV fallback (it reads from
the canonical Redis snapshot for its live-data overlay).
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
from pathlib import Path

import pandas as pd
import redis

_log = logging.getLogger(__name__)

# Local snapshot tier: a gzipped JSON mirror of the runtime Redis keyspace,
# written by redis-loader/dump_snapshot.py (see `just snapshot`).
SNAPSHOT_ENV = "NSQ_SNAPSHOT"
SNAPSHOT_DEFAULT_PATH = "data/nsq_snapshot.json.gz"

# CDSCO publicNsqDrugTable field name -> CSV-era column name used
# throughout analytics/app.py and simulator/app.py.
FIELD_MAP = {
    "str_product_name": "Name of Product",
    "str_batch_no": "Batch No",
    "dt_manufacturing_date": "Manufacturing Date",
    "dt_expiry_date": "Expiry Date",
    "str_manufactured_by": "Manufactured By",
    "str_nsq_result": "NSQ Result",
    "str_reporting_source": "Reporting Source",
    "str_reported_by_lab_or_state": "Reporting by Lab/State",
    "dt_reporting_month_year": "Reporting Month & Year",
}

# CSV column -> CDSCO key. Inverse of the above (plus the two CSV-only
# columns Index and Source, which pass through).
_CSV_TO_CDSCO = {
    "Index":                    "index",
    "Name of Product":          "str_product_name",
    "Batch No":                 "str_batch_no",
    "Mfg":                      "dt_manufacturing_date",
    "Exp":                      "dt_expiry_date",
    "Manufactured By":          "str_manufactured_by",
    "NSQ Result":               "str_nsq_result",
    "Reporting Source":         "str_reporting_source",
    "Reporting by Lab/State":   "str_reported_by_lab_or_state",
    "Reporting Month & Year":   "dt_reporting_month_year",
    "Source":                   "source",
}


def get_redis_client(url: str | None = None) -> redis.Redis:
    url = url or os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError(
            "REDIS_URL is not set. Both services expect a Redis connection "
            "string (see .env.example)."
        )
    return redis.from_url(url, decode_responses=True)


# ---------------------------------------------------------------------------
# Local snapshot tier
# ---------------------------------------------------------------------------

# Module-level memo: the parsed snapshot dict plus the (resolved path,
# mtime_ns, size) triple it was read at. Re-reads only when the file
# changes on disk, so a Streamlit rerun costs an os.stat, not a gunzip.
_snapshot_cache: dict | None = None
_snapshot_stat: tuple[str, int, int] | None = None


def _warn_redis_unavailable(exc: Exception) -> None:
    _log.warning(
        "Redis unavailable (%s: %s) — falling back to the local snapshot. "
        "If this is the Upstash free plan, the monthly command quota may "
        "be exhausted; data will be as fresh as the last snapshot.",
        type(exc).__name__, exc,
    )


def load_snapshot() -> dict | None:
    """Return the parsed local snapshot (see dump_snapshot.py), or None if
    absent/unreadable. Never raises. A path pointing at a directory also
    yields None — Docker creates a directory at a single-file bind mount's
    target when the source file is missing on the host."""
    global _snapshot_cache, _snapshot_stat
    path = Path(os.environ.get(SNAPSHOT_ENV, SNAPSHOT_DEFAULT_PATH))
    try:
        if path.is_dir():
            raise OSError(f"{path} is a directory")
        st = path.stat()
        stat = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        _snapshot_cache = None
        _snapshot_stat = None
        return None
    if _snapshot_cache is not None and _snapshot_stat == stat:
        return _snapshot_cache
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("Snapshot at %s unreadable (%s) — ignoring it", path, exc)
        _snapshot_cache = None
        _snapshot_stat = None
        return None
    _snapshot_cache = snap
    _snapshot_stat = stat
    return snap


def _snapshot_sections() -> dict:
    snap = load_snapshot() or {}
    sections = snap.get("sections")
    return sections if isinstance(sections, dict) else {}


def _load_from_redis(r: redis.Redis) -> pd.DataFrame:
    """Fetch every nsq:record:* hash and return it as a DataFrame."""
    ids = r.smembers("nsq:records")
    if not ids:
        return pd.DataFrame(columns=list(FIELD_MAP.values()))

    # Capture a stable ordered list so the per-row record id stays aligned
    # with the pipeline results (set iteration order is consistent within a
    # process, but materializing once makes the pairing explicit).
    id_list = list(ids)
    pipe = r.pipeline()
    for rid in id_list:
        pipe.hgetall(f"nsq:record:{rid}")
    rows = pipe.execute()

    df = pd.DataFrame(rows)
    df = df.rename(columns=FIELD_MAP)
    # Carry the Redis record id (the key of nsq:record:<rid>) so downstream
    # code can join nsq:prediction:<rid> on the same stable rid. The CDSCO
    # `index` field is NOT a stable join key across mixed data loads (it
    # collides between a live CDSCO fetch and a CSV load); the rid is.
    df["record_id"] = id_list
    return df


def _load_from_csv(path: Path) -> pd.DataFrame:
    """Offline fallback: read the CSV directly and apply the same
    column renames the Redis path uses. Mfg/Exp are NOT in FIELD_MAP
    so the analytics app will see them as Mfg/Exp (CDSCO writes them
    as dt_manufacturing_date / dt_expiry_date with raw date strings
    anyway) — analytics never reads these columns regardless of
    which path produced the DataFrame."""
    df = pd.read_csv(path)
    # Two-step rename: CSV -> CDSCO -> CSV-era (FIELD_MAP).
    df = df.rename(columns={k: v for k, v in _CSV_TO_CDSCO.items() if k in df.columns})
    df = df.rename(columns=FIELD_MAP)
    return df


def _load_from_snapshot() -> pd.DataFrame:
    """Build the records DataFrame out of the local snapshot, mirroring
    what _load_from_redis returns: FIELD_MAP renames plus a record_id
    column aligned with the ordered record_ids list, so the
    nsq:prediction:<rid> join keeps working on the fallback path."""
    sections = _snapshot_sections()
    id_list = sections.get("record_ids") or []
    records = sections.get("records") or {}
    rows = [records.get(rid) for rid in id_list if records.get(rid)]
    if not rows:
        return pd.DataFrame(columns=list(FIELD_MAP.values()))
    df = pd.DataFrame(rows)
    df = df.rename(columns=FIELD_MAP)
    # Keep ids aligned with the surviving rows (a rid missing from the
    # records dict drops both sides of the pair together).
    kept = [rid for rid in id_list if records.get(rid)]
    df["record_id"] = kept
    return df


# The one canonical CSV name in the codebase — kept identical to the
# justfile's CSV variable so the loader recipes and this offline fallback
# never point at different files (they used to: three names, one file).
_DEFAULT_CSV = "data/CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv"


def load_dataframe(client: redis.Redis | None = None) -> pd.DataFrame:
    """Fetch every nsq:record:* hash and return it as a DataFrame.

    Column names match the original CSV export so existing analytics
    and simulator logic (which was written against those names) keeps
    working unchanged.

    Tiered: live Redis first; on RedisError (e.g. the Upstash monthly
    quota) or an empty dataset, the local snapshot at $NSQ_SNAPSHOT; if
    no snapshot exists, the host-side CSV at $NSQ_CSV — an offline
    convenience whose default is the same cumulative export the justfile's
    CSV variable names, so the loader recipes and this fallback can never
    disagree about which file is canonical. The service images do not
    ship it (the Dockerfiles copy only app.py + shared/), so in containers
    the CSV tier is a no-op and an empty frame is what surfaces.
    """
    try:
        r = client or get_redis_client()
        df = _load_from_redis(r)
    except (RuntimeError, redis.RedisError) as exc:
        _warn_redis_unavailable(exc)
        df = pd.DataFrame(columns=list(FIELD_MAP.values()))

    if not df.empty:
        # Any Redis fields not in FIELD_MAP (future-proofing) pass
        # through unchanged rather than being dropped.
        return df

    # Empty/failing Redis — try the snapshot, then the host-side CSV
    # fallback (a partial slice, absent inside the service images).
    snap_df = _load_from_snapshot()
    if not snap_df.empty:
        return snap_df

    csv_path = Path(os.environ.get("NSQ_CSV", _DEFAULT_CSV))
    if not csv_path.is_file():
        return df
    return _load_from_csv(csv_path)


def load_predictions(client: redis.Redis | None = None) -> dict[str, dict[str, str]]:
    """Read every nsq:prediction:<rid> hash, keyed by the record id it
    belongs to. Field names are raw loader names (raw_company, canonical,
    state, website, ontology_key, ...).

    Falls back to the local snapshot when Redis is unavailable, then
    {} — the same tiering as load_dataframe.
    """
    try:
        r = client or get_redis_client()
        ids = r.smembers("nsq:records")
        if not ids:
            return {}
        pipe = r.pipeline()
        for rid in ids:
            pipe.hgetall(f"nsq:prediction:{rid}")
        rows = pipe.execute()
    except (RuntimeError, redis.RedisError) as exc:
        _warn_redis_unavailable(exc)
        return dict(_snapshot_sections().get("predictions") or {})
    return {rid: row for rid, row in zip(ids, rows) if row}


def load_meta(client: redis.Redis | None = None) -> dict:
    try:
        r = client or get_redis_client()
        return r.hgetall("nsq:meta")
    except (RuntimeError, redis.RedisError) as exc:
        _warn_redis_unavailable(exc)
        return dict(_snapshot_sections().get("meta") or {})


def _decode_geo_payload(payload: str | bytes, encoding: str) -> dict:
    """Decode a stored GeoJSON payload the way load_geojson_redis.py
    wrote it: either gzip+base64 (see its default) or plain text."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if encoding == "gzip+base64":
        text = gzip.decompress(base64.b64decode(payload)).decode("utf-8")
    else:
        text = payload
    return json.loads(text)


def load_geojson(url: str | None = None, key: str = "geo:india_states") -> dict | None:
    """Fetch a GeoJSON payload previously pushed by
    redis-loader/load_geojson_redis.py, and return it as a parsed dict.

    Returns None if the key isn't present (e.g. it hasn't been loaded
    yet). Falls back to the snapshot's geo section when Redis is
    unavailable. Uses its own raw-bytes connection since the stored
    payload may be gzip-compressed (not plain text), independent of the
    decode_responses setting used elsewhere in this module.
    """
    try:
        url = url or os.environ.get("REDIS_URL")
        if not url:
            raise RuntimeError(
                "REDIS_URL is not set. Both services expect a Redis connection "
                "string (see .env.example)."
            )
        raw_client = redis.from_url(url, decode_responses=False)

        payload = raw_client.get(key)
        if payload is None:
            return None

        meta = raw_client.hgetall(f"{key}:meta") or {}
        encoding = meta.get(b"encoding", b"gzip+base64").decode("utf-8")
        return _decode_geo_payload(payload, encoding)
    except (RuntimeError, redis.RedisError) as exc:
        _warn_redis_unavailable(exc)
        entry = (_snapshot_sections().get("geo") or {}).get(key)
        if not entry:
            return None
        try:
            return _decode_geo_payload(
                entry.get("payload", ""), entry.get("encoding", "gzip+base64"))
        except (ValueError, OSError) as decode_exc:
            _log.warning("Snapshot geo entry %s unreadable (%s) — ignoring it",
                         key, decode_exc)
            return None
