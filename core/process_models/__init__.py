"""Framework-agnostic manufacturing process models for the NSQ simulator.

Each module here is a pure-Python domain model: typed CPP inputs in,
typed CQA + failure-mode outputs out. No Streamlit, no FastAPI, no Redis
imports — so the same model is callable from the API, from tests, and
(eventually) from a job worker. A future pharmacokinetic / mechanistic
model can replace the illustrative rules in any module without touching
the API or UI, because the model is the seam.

Route registry
--------------
Each telmisartan route module exports a uniform contract:
    ROUTE_ID, ROUTE_LABEL, ROUTE_DESCRIPTION, STAGES, simulate(params: dict) -> dict
ROUTES maps route_id -> the module, so the API and UI can enumerate routes and
dispatch a simulation with no route-specific code. Add a new route by dropping
a module here and registering it in ROUTES.
"""
from __future__ import annotations

from . import telmisartan, telmisartan_dc
from .telmisartan import (
    STAGE1_RANGES,
    STAGE2_RANGES,
    FailureMode,
    Severity,
    Stage1Params,
    Stage1Result,
    Stage2Params,
    Stage2Result,
    simulate_stage1,
    simulate_stage2,
)
from .telmisartan_dc import (
    DC_STAGE1_RANGES,
    DC_STAGE2_RANGES,
    DCStage1Params,
    DCStage1Result,
    DCStage2Params,
    DCStage2Result,
    simulate_dc_stage1,
    simulate_dc_stage2,
)

# route_id -> route module. Each module exposes ROUTE_ID/ROUTE_LABEL/
# ROUTE_DESCRIPTION/STAGES/simulate. The API enumerates this to build the
# route selector and dispatches POST /v1/simulate/telmisartan/{route_id}.
ROUTES = {
    telmisartan.ROUTE_ID: telmisartan,
    telmisartan_dc.ROUTE_ID: telmisartan_dc,
}


def route_metadata() -> list[dict]:
    """Return metadata for every route, for GET /v1/simulate/telmisartan/routes."""
    return [
        {
            "id": m.ROUTE_ID,
            "label": m.ROUTE_LABEL,
            "description": m.ROUTE_DESCRIPTION,
            "stages": m.STAGES,
        }
        for m in ROUTES.values()
    ]


__all__ = [
    # NaOH fluid-bed route
    "STAGE1_RANGES",
    "STAGE2_RANGES",
    "FailureMode",
    "Severity",
    "Stage1Params",
    "Stage1Result",
    "Stage2Params",
    "Stage2Result",
    "simulate_stage1",
    "simulate_stage2",
    # Direct-compression route
    "DC_STAGE1_RANGES",
    "DC_STAGE2_RANGES",
    "DCStage1Params",
    "DCStage1Result",
    "DCStage2Params",
    "DCStage2Result",
    "simulate_dc_stage1",
    "simulate_dc_stage2",
    # Route registry
    "ROUTES",
    "route_metadata",
    "telmisartan",
    "telmisartan_dc",
]