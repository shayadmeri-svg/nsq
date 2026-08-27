"""FastAPI entry point for the manufacturing process simulator.

Runs independently of the Streamlit intelligence app. Exposes the pure
process models under a route-aware contract:

    GET  /v1/simulate/telmisartan/routes
        -> [{id, label, description, stages: [{id, label, cpps, cqas}]}, ...]
    GET  /v1/simulate/telmisartan/{route_id}/metadata
        -> one route's metadata (slider bounds + optima + CQA tiles)
    POST /v1/simulate/telmisartan/{route_id}
        body: flat {cpp_name: value} dict for every CPP the route declares
        -> {route_id, route_label, stages: [...], overall_severity,
            overall_failure_mode}

The model lives in simulator/process_models/ (framework-agnostic); this file
is a thin adapter that validates CPPs against each route's declared ranges and
serialises — it contains no domain rules of its own, so a model change never
touches this file and a UI change never touches the model. Adding a route is a
one-line registration in process_models/__init__.py (ROUTES); this file does
not change.

Run:
    cd simulator && .venv/bin/uvicorn api_main:app --reload --port 8010

The React frontend (or the standalone HTML prototype) calls these endpoints;
CORS is enabled for local development.
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from process_models import ROUTES, route_metadata


app = FastAPI(
    title="NSQ Manufacturing Process Simulator API",
    version="0.2.0",
    description=(
        "Pure process-model endpoints for in-silico manufacturing simulation. "
        "Each route takes Critical Process Parameters (CPPs) and returns "
        "Critical Quality Attributes (CQAs) plus per-stage and overall "
        "failure-mode verdicts. Routes are selectable — telmisartan currently "
        "ships a NaOH fluid-bed route and a Direct-Compression route. The model "
        "is the seam — these rules are illustrative and replaceable."
    ),
)

# Local-dev CORS. In production this is scoped to the frontend origin via env.
_origins = os.environ.get("SIMULATOR_CORS_ORIGINS", "http://localhost:5173,http://localhost:8010,http://localhost:8000,http://127.0.0.1:8010")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _route_or_404(route_id: str):
    mod = ROUTES.get(route_id)
    if mod is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown route '{route_id}'. Available: {list(ROUTES)}",
        )
    return mod


def _validate_cpp_ranges(route_id: str, payload: dict) -> dict:
    """Coerce + range-check every CPP the route declares against its STAGES
    metadata. Returns a clean float dict ready for simulate(). Missing CPPs
    fall back to the declared default so a partial body still simulates."""
    mod = _route_or_404(route_id)
    clean: dict[str, float] = {}
    for stage in mod.STAGES:
        for cpp in stage["cpps"]:
            name = cpp["name"]
            val = payload.get(name, cpp["default"])
            try:
                val = float(val)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"CPP '{name}' must be numeric, got {payload.get(name)!r}",
                ) from exc
            lo, hi = float(cpp["min"]), float(cpp["max"])
            if val < lo or val > hi:
                raise HTTPException(
                    status_code=422,
                    detail=f"CPP '{name}'={val} out of range [{lo}, {hi}]",
                )
            clean[name] = val
    return clean


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "routes": list(ROUTES)}


@app.get("/")
@app.get("/simulator")
def simulator_page() -> FileResponse:
    """Serve the standalone API-backed simulator page (route selector + sliders
    that call this API). Open http://localhost:8010/simulator in the browser."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "simulator.html"))


@app.get("/v1/simulate/telmisartan/routes")
def telmisartan_routes() -> list[dict]:
    """List every available route with full stage/CPP/CQA metadata. The
    frontend builds the route selector and all slider bounds from this one
    response — no hardcoded ranges in the UI."""
    return route_metadata()


@app.get("/v1/simulate/telmisartan/{route_id}/metadata")
def telmisartan_route_metadata(route_id: str) -> dict:
    """Single route's metadata (slider bounds + optima + CQA tiles)."""
    mod = _route_or_404(route_id)
    return {
        "id": mod.ROUTE_ID,
        "label": mod.ROUTE_LABEL,
        "description": mod.ROUTE_DESCRIPTION,
        "stages": mod.STAGES,
    }


@app.post("/v1/simulate/telmisartan/{route_id}")
async def telmisartan_simulate(route_id: str, req: Request) -> dict:
    """Run the route's simulate() with a flat {cpp_name: value} body.

    CPPs are validated against the route's declared ranges (422 on
    out-of-range); missing CPPs fall back to declared defaults. Returns
    per-stage CQAs + severity/failure-mode and an overall verdict (the worst
    stage severity). The shape is identical across routes, so the UI renders
    any route from its metadata alone.
    """
    mod = _route_or_404(route_id)
    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object of CPPs.")
    clean = _validate_cpp_ranges(route_id, payload)
    return mod.simulate(clean)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_main:app", host="0.0.0.0", port=8010, reload=True)