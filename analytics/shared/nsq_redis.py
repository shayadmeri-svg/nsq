"""Load NSQ alert records from Redis into a pandas DataFrame.

Reads the keys written by redis-loader/load_nsq_redis.py:
  nsq:records            -> SET of record ids
  nsq:record:<id>        -> HASH of one row (CDSCO publicNsqDrugTable field names)

Field names coming out of Redis use the CDSCO API's own prefixes
(str_product_name, dt_reporting_month_year, ...). This module renames
them to the column names the existing analytics/simulator code already
expects (the same names the original CSV export used), so downstream
logic in both apps is unchanged.

If Redis is unreachable or returns an empty dataset, load_dataframe()
falls back to reading the CSV specified by NSQ_CSV (default
'data/data Jan25_May26.csv') directly via pandas. This keeps the
analytics app usable offline; the simulator doesn't use the fallback
(simulator reads from the canonical Redis snapshot for its live-data
overlay).
"""

from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path

import pandas as pd
import redis

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


def _load_from_redis(r: redis.Redis) -> pd.DataFrame:
    """Fetch every nsq:record:* hash and return it as a DataFrame."""
    ids = r.smembers("nsq:records")
    if not ids:
        return pd.DataFrame(columns=list(FIELD_MAP.values()))

    pipe = r.pipeline()
    for rid in ids:
        pipe.hgetall(f"nsq:record:{rid}")
    rows = pipe.execute()

    df = pd.DataFrame(rows)
    df = df.rename(columns=FIELD_MAP)
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


def load_dataframe(client: redis.Redis | None = None) -> pd.DataFrame:
    """Fetch every nsq:record:* hash and return it as a DataFrame.

    Column names match the original CSV export so existing analytics
    and simulator logic (which was written against those names) keeps
    working unchanged.

    Falls back to reading the CSV at $NSQ_CSV (default
    'data/data Jan25_May26.csv') when Redis is unreachable or returns
    an empty dataset — so the analytics app still works offline.
    """
    try:
        r = client or get_redis_client()
        df = _load_from_redis(r)
    except (RuntimeError, redis.RedisError):
        df = pd.DataFrame(columns=list(FIELD_MAP.values()))

    if not df.empty:
        # Any Redis fields not in FIELD_MAP (future-proofing) pass
        # through unchanged rather than being dropped.
        return df

    # Empty Redis — try the CSV fallback.
    csv_path = Path(os.environ.get("NSQ_CSV", "data/data Jan25_May26.csv"))
    if not csv_path.is_file():
        return df
    return _load_from_csv(csv_path)


def load_meta(client: redis.Redis | None = None) -> dict:
    r = client or get_redis_client()
    return r.hgetall("nsq:meta")


def load_geojson(url: str | None = None, key: str = "geo:india_states") -> dict | None:
    """Fetch a GeoJSON payload previously pushed by
    redis-loader/load_geojson_redis.py, and return it as a parsed dict.

    Returns None if the key isn't present (e.g. it hasn't been loaded yet).
    Uses its own raw-bytes connection since the stored payload may be
    gzip-compressed (not plain text), independent of the decode_responses
    setting used elsewhere in this module.
    """
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

    if encoding == "gzip+base64":
        text = gzip.decompress(base64.b64decode(payload)).decode("utf-8")
    else:
        text = payload.decode("utf-8")

    return json.loads(text)
