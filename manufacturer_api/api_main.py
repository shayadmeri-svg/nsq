"""FastAPI entry point for the manufacturer (Q-engine) client app.

Replaces the Streamlit render layer in ``manufacturer/app.py``. The React
frontend (``web/``) calls these endpoints; this service wraps the existing
headless cores — ``diagnostics_core.build_diagnosis``, ``tenant_scope``,
``tenants``, and ``ui.charts`` (Plotly figure builders) — without
duplicating business logic. There is no Streamlit dependency here.

Endpoints (all JSON):

    GET /health
        -> {status, redis_ready}
    GET /api/manufacturer/config
        -> {tenants: [{key, canonical, city, ontology_key}], personas: [...]}
    GET /api/manufacturer/{tenant_key}/dashboard
        -> {tenant, period, kpis: [...], charts: {by_type, over_time, by_form,
            form_vs_issue}, issues: [{id, product, batch, lab, month, nsq_result,
            failure_category, form}], issue_count, empty}
    GET /api/manufacturer/{tenant_key}/diagnostics/{issue_id}?persona=QA
        -> {diagnosis: <serialised Diagnosis>, issue_id, tenant, persona}

Data source: the ``nsq:*`` Redis keyspace via ``shared/nsq_redis.py`` (CSV
fallback when Redis is empty/unreachable), enriched by
``shared/data_loader._load_and_preprocess`` (the pure, non-Streamlit core).
The enriched frame is cached in-process for ``FRAME_TTL_S`` seconds to avoid
re-running the enrichment pipeline on every request (mirrors the Streamlit
apps' ``@st.cache_data(ttl=300)``).

Run:
    cd manufacturer_api && .venv/bin/python -m uvicorn api_main:app --port 8001 --reload

CORS is enabled for local development (the Vite dev server at :5173); in
production the nginx gateway makes the frontend same-origin.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import sys
import time
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# Resolve the vendored shared/ modules and the local ui/ package — mirrors
# manufacturer/app.py's sys.path setup so the flat imports
# (``import tenants``, ``from ui.charts import ...``) resolve.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "shared"))
sys.path.insert(0, _HERE)

import data_loader  # noqa: E402
from diagnostics_core import Diagnosis, build_diagnosis  # noqa: E402
from tenant_scope import tenant_display, tenant_period, tenant_product_count  # noqa: E402
from tenants import REGISTRY, Tenant, get_tenant  # noqa: E402
from ui.charts import (  # noqa: E402
    bar_by_form,
    donut_issue_by_type,
    heatmap_form_vs_issue,
    line_over_time,
)

# Persona constants — mirror manufacturer/auth.PERSONAS. Defined locally
# (not imported from auth.py) because auth.py imports Streamlit at module
# level, which is unavailable in this service's image.
PERSONAS: tuple[str, ...] = ("QA", "Regulatory", "Executive")

FRAME_TTL_S = 300.0  # mirrors the Streamlit apps' @st.cache_data ttl

# In-process enriched-frame cache: (expires_at_monotonic, df). Single-worker
# uvicorn is the default; for multi-worker deploys each worker caches its own
# copy (acceptable — the enrichment is deterministic and read-only).
_frame_cache: tuple[float, pd.DataFrame] | None = None


def _cached_frame() -> pd.DataFrame:
    """Return the enriched NSQ frame, recomputing at most every FRAME_TTL_S."""
    global _frame_cache
    now = time.monotonic()
    if _frame_cache is None or now >= _frame_cache[0]:
        _frame_cache = (now + FRAME_TTL_S, data_loader._load_and_preprocess())
    return _frame_cache[1]


def _scoped_frame(tenant: Tenant) -> pd.DataFrame:
    """Enriched frame filtered to the tenant's rows on Mfg_Ontology_Key."""
    df = _cached_frame()
    if df.empty or "Mfg_Ontology_Key" not in df.columns:
        return df.iloc[0:0]
    return df[df["Mfg_Ontology_Key"] == tenant.ontology_key].copy()


def _tenant_or_404(tenant_key: str) -> Tenant:
    t = get_tenant(tenant_key)
    if t is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown tenant {tenant_key!r}. Available: "
                f"{[t.key for t in REGISTRY]}"
            ),
        )
    return t


def _col(row: pd.Series, name: str, default: str = "—") -> str:
    """Read a frame column with a dash fallback (mirrors diagnostics_core._col)."""
    v = row.get(name, default)
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return default
    return str(v)


def _issue_id(row: pd.Series, idx: int) -> str:
    """Stable identifier for an issue row: the Redis record_id if present,
    else a positional ``row-<idx>`` fallback."""
    rid = row.get("record_id")
    if rid is not None and not (isinstance(rid, float) and pd.isna(rid)) and str(rid).strip():
        return str(rid)
    return f"row-{idx}"


def _resolve_issue_row(df: pd.DataFrame, issue_id: str) -> pd.Series:
    """Find the row for ``issue_id`` by record_id, then by the row-<idx> fallback."""
    if "record_id" in df.columns:
        mask = df["record_id"].astype(str) == issue_id
        if mask.any():
            return df[mask].iloc[0]
    if issue_id.startswith("row-"):
        try:
            i = int(issue_id[len("row-"):])
            if 0 <= i < len(df):
                return df.iloc[i]
        except ValueError:
            pass
    raise HTTPException(
        status_code=404,
        detail=f"Issue {issue_id!r} not found for this tenant.",
    )


def _json_safe(obj):
    """Recursively convert a dataclass/enum/tuple/numpy structure to plain
    JSON-safe Python. Used to serialise ``Diagnosis`` (which nests ``Drug``,
    ``Mitigation``, ``Provenance``, ``MethodDiff`` with ``dict[Pharmacopeia,
    ...]`` keys, etc.) without relying on json's enum/tuple handling."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, enum.Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _json_safe(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {_json_safe(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    # numpy / pandas scalars
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return obj.item()
        except Exception:
            return obj
    return obj


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate Redis connectivity on startup (mirrors engine/api_main.py).
    url = os.environ.get("REDIS_URL")
    ready = False
    if url:
        try:
            import redis

            ready = bool(redis.from_url(url, decode_responses=True).ping())
        except Exception:
            ready = False
    app.state.redis_ready = ready
    yield


app = FastAPI(
    title="Q-engine Manufacturer API",
    version="0.1.0",
    description=(
        "Client-facing Q-engine endpoints for the manufacturer app. Wraps the "
        "headless diagnostics/GMP/pharmacopeia cores and the Plotly chart "
        "builders; the React frontend renders the JSON payloads."
    ),
    lifespan=lifespan,
)

# Local-dev CORS. In production the nginx gateway makes the frontend
# same-origin, so this is only used for the Vite dev server.
_origins = os.environ.get(
    "MANUFACTURER_API_CORS_ORIGINS",
    "http://localhost:5173,http://localhost:8001,http://localhost:8080",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok" if app.state.redis_ready else "degraded",
        "redis_ready": app.state.redis_ready,
    }


@app.get("/api/manufacturer/config")
def config():
    """Sign-in choices: the tenant registry + the persona set."""
    return {
        "tenants": [
            {"key": t.key, "canonical": t.canonical, "city": t.city, "ontology_key": t.ontology_key}
            for t in REGISTRY
        ],
        "personas": list(PERSONAS),
    }


@app.get("/api/manufacturer/{tenant_key}/dashboard")
def dashboard(tenant_key: str):
    tenant = _tenant_or_404(tenant_key)
    df = _scoped_frame(tenant)
    canonical, city = tenant_display(tenant)

    if df.empty:
        return {
            "tenant": {"key": tenant.key, "canonical": canonical, "city": city},
            "period": "—",
            "kpis": [
                {"label": "NSQ alerts", "value": 0, "help": "NSQ alerts for this manufacturer"},
                {"label": "Products", "value": 0, "help": "Distinct products"},
                {"label": "Period", "value": "—", "help": "Reporting period span"},
            ],
            "charts": {"by_type": None, "over_time": None, "by_form": None, "form_vs_issue": None},
            "issues": [],
            "issue_count": 0,
            "empty": True,
        }

    issues = []
    for i, (_, row) in enumerate(df.iterrows()):
        issues.append({
            "id": _issue_id(row, i),
            "product": _col(row, "Product_Name_Canonical", _col(row, "Name of Product")),
            "batch": _col(row, "Batch No"),
            "lab": _col(row, "Reporting by Lab/State"),
            "month": _col(row, "Reporting Month & Year"),
            "nsq_result": _col(row, "NSQ Result"),
            "failure_category": _col(row, "Failure_Category"),
            "form": _col(row, "Form type"),
        })

    def _fig(builder):
        fig = builder(df)
        if fig is None:
            return None
        # fig.to_json() runs Plotly's own encoder (handles tuples / numpy
        # scalars that FastAPI's jsonable_encoder stumbles on); json.loads
        # yields plain dict/list/primitives for trivial re-encoding.
        return json.loads(fig.to_json())

    return {
        "tenant": {"key": tenant.key, "canonical": canonical, "city": city},
        "period": tenant_period(df),
        "kpis": [
            {"label": "NSQ alerts", "value": int(len(df)), "help": "NSQ alerts for this manufacturer"},
            {"label": "Products", "value": tenant_product_count(df), "help": "Distinct products"},
            {"label": "Period", "value": tenant_period(df), "help": "Reporting period span"},
        ],
        "charts": {
            "by_type": _fig(donut_issue_by_type),
            "over_time": _fig(line_over_time),
            "by_form": _fig(bar_by_form),
            "form_vs_issue": _fig(heatmap_form_vs_issue),
        },
        "issues": issues,
        "issue_count": len(issues),
        "empty": False,
    }


@app.get("/api/manufacturer/{tenant_key}/diagnostics/{issue_id}")
def diagnostics(
    tenant_key: str,
    issue_id: str,
    persona: str = Query("QA"),
):
    tenant = _tenant_or_404(tenant_key)
    if persona not in PERSONAS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown persona {persona!r}. Expected one of {list(PERSONAS)}.",
        )
    df = _scoped_frame(tenant)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No NSQ issues for tenant {tenant_key!r}.",
        )
    row = _resolve_issue_row(df, issue_id)
    diag: Diagnosis = build_diagnosis(row, df)
    canonical, city = tenant_display(tenant)
    return {
        "diagnosis": _json_safe(diag),
        "issue_id": issue_id,
        "tenant": {"key": tenant.key, "canonical": canonical, "city": city},
        "persona": persona,
    }