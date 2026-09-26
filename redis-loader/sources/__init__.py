"""Public-data sources for the molecule universe and site directory.

SOURCES maps a source key to its metadata and run function. fetch_source.py
is the CLI; the admin job runner and the justfile both call it.
"""

from __future__ import annotations

from typing import Any, Callable

from . import clinical_trials, ema, fda_sites, orange_book, purple_book
from .common import Ctx

CDSCO_META = {
    "title": "CDSCO NSQ alerts",
    "publisher": "Central Drugs Standard Control Organisation (India)",
    "url": "https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable",
    "page": "https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug",
    "cadence": "monthly notifications; checked daily",
    "feeds": ["NSQ alerts", "Molecule candidates", "Site directory"],
}

SOURCES: dict[str, dict[str, Any]] = {
    "orange_book": {**orange_book.META, "run": orange_book.run, "group": "molecules", "min_interval_days": 7},
    "purple_book": {**purple_book.META, "run": purple_book.run, "group": "molecules", "min_interval_days": 7},
    "ema": {**ema.META, "run": ema.run, "group": "molecules"},
    "clinical_trials": {**clinical_trials.META, "run": clinical_trials.run, "group": "demand"},
    "fda_establishments": {**fda_sites.DECRS, "run": fda_sites.run_establishments, "group": "sites", "min_interval_days": 3},
    "fda_import_alerts": {**fda_sites.IMPORT_ALERT, "run": fda_sites.run_import_alerts, "group": "sites"},
    "fda_recalls": {**fda_sites.RECALLS, "run": fda_sites.run_recalls, "group": "sites"},
}


def public_meta() -> dict[str, dict[str, Any]]:
    out = {k: {kk: vv for kk, vv in v.items() if not callable(vv)} for k, v in SOURCES.items()}
    out["cdsco"] = {**CDSCO_META, "group": "alerts"}
    return out


__all__ = ["SOURCES", "Ctx", "public_meta"]
