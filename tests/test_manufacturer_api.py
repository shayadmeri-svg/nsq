"""Tests for the manufacturer_api FastAPI service (the React frontend's backend).

Covers the JSON contract the ``web/`` React app consumes:
  - /health            — status + redis_ready
  - /api/manufacturer/config  — tenant registry + persona set (sign-in choices)
  - /api/manufacturer/{tenant}/dashboard — KPIs (8/6/period), 4 chart specs,
    8 issues each with a stable id
  - /api/manufacturer/{tenant}/diagnostics/{issue_id} — a serialised Diagnosis
    (product, drug-or-generic_fallback, method_diffs, mitigations, synthesis_gap)
  - routing errors: 404 unknown tenant/issue, 400 unknown persona

Integration tests skip when Redis is unreachable (the canonical store; the
CSV fallback would also work but the suite standardises on Redis per
test_tenant_scope.py).

Runnable both as ``python tests/test_manufacturer_api.py`` and via pytest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MFR_API = REPO / "manufacturer_api"

sys.path.insert(0, str(MFR_API))
import api_main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TENANT = "regent-ajanta-biotech"
EXPECTED_ALERTS = 8
EXPECTED_PRODUCTS = 6


def _redis_reachable() -> bool:
    url = os.environ.get("REDIS_URL")
    if not url:
        return False
    try:
        import redis

        return bool(redis.from_url(url, decode_responses=True).ping())
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    with TestClient(api_main.app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body and "redis_ready" in body
    assert body["status"] in ("ok", "degraded")


def test_config(client):
    r = client.get("/api/manufacturer/config")
    assert r.status_code == 200
    body = r.json()
    assert [t["key"] for t in body["tenants"]] == [TENANT]
    t = body["tenants"][0]
    assert t["canonical"] == "Regent Ajanta Biotech"
    assert t["ontology_key"] == "regent ajanta"
    assert body["personas"] == ["QA", "Regulatory", "Executive"]


def test_dashboard_unknown_tenant_404(client):
    assert client.get("/api/manufacturer/nope/dashboard").status_code == 404


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_dashboard_payload(client):
    r = client.get(f"/api/manufacturer/{TENANT}/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert d["empty"] is False
    assert d["tenant"]["key"] == TENANT
    assert d["period"] == "Jan 2025 – Jun 2026"

    kpis = {k["label"]: k["value"] for k in d["kpis"]}
    assert kpis["NSQ alerts"] == EXPECTED_ALERTS
    assert kpis["Products"] == EXPECTED_PRODUCTS

    assert set(d["charts"].keys()) == {"by_type", "over_time", "by_form", "form_vs_issue"}
    # Each chart is a Plotly figure dict (or null); the four tenant charts are
    # non-null for Regent's data.
    assert all(d["charts"][k] is not None for k in d["charts"])

    assert d["issue_count"] == EXPECTED_ALERTS == len(d["issues"])
    first = d["issues"][0]
    assert first["id"] and first["product"]  # stable id + product present
    for issue in d["issues"]:
        assert {"id", "product", "batch", "lab", "month", "nsq_result", "failure_category", "form"} <= set(issue)


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_diagnostics_payload(client):
    d = client.get(f"/api/manufacturer/{TENANT}/dashboard").json()
    issue_id = d["issues"][0]["id"]
    r = client.get(f"/api/manufacturer/{TENANT}/diagnostics/{issue_id}?persona=QA")
    assert r.status_code == 200
    body = r.json()
    assert body["issue_id"] == issue_id
    assert body["persona"] == "QA"
    dx = body["diagnosis"]
    # Identity + data-informed signals.
    assert dx["product"] and dx["tenant_alert_count"] == EXPECTED_ALERTS
    assert isinstance(dx["dominant_failures"], list)
    assert isinstance(dx["method_diffs"], list)
    assert isinstance(dx["mitigations"], list)
    assert dx["synthesis_gap"] is True
    # Either a curated Drug (api_id set, generic_fallback False) or the
    # generic fallback (generic_text present).
    assert (dx["api_id"] is not None and dx["generic_fallback"] is False) or dx["generic_fallback"] is True
    # Provenance round-trips as JSON-safe dicts (no enum objects leak through).
    if dx["method_diffs"]:
        keys = list(dx["method_diffs"][0]["methods"].keys())
        assert all(isinstance(k, str) for k in keys)  # "IP 2026" / "Ph. Eur." / "USP"


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_diagnostics_errors(client):
    d = client.get(f"/api/manufacturer/{TENANT}/dashboard").json()
    issue_id = d["issues"][0]["id"]
    # Unknown persona -> 400.
    assert client.get(f"/api/manufacturer/{TENANT}/diagnostics/{issue_id}?persona=Scientist").status_code == 400
    # Unknown issue -> 404.
    assert client.get(f"/api/manufacturer/{TENANT}/diagnostics/does-not-exist").status_code == 404


if __name__ == "__main__":
    # Minimal standalone runner (does not exercise lifespan skip logic).
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    with TestClient(api_main.app) as c:
        for name, fn in [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]:
            try:
                import inspect
                if "client" in inspect.signature(fn).parameters:
                    fn(c)
                else:
                    fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                print(f"  FAIL  {name}: {e}")
            except Exception as e:  # noqa
                print(f"  ERROR {name}: {type(e).__name__}: {e}")