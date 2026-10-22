"""Public-data sources for the molecule universe and site directory.

SOURCES maps a source key to its metadata and run function. fetch_source.py
is the CLI; the admin job runner and the justfile both call it.
"""

from __future__ import annotations

from typing import Any, Callable

from . import api_filings, jp, cdsco_plants, cdsco_wc, chembl, edqm_kd, fda_dissolution, fda_labels, health_signals, ord, clinical_trials, ema, eudragmdp, fda_inspections, fda_sites, orange_book, patent_families, ph_int, pubchem, pubchem_synonyms, purple_book
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
    "pubchem": {**pubchem.META, "run": pubchem.run, "group": "chemistry"},
    "pubchem_synonyms": {**pubchem_synonyms.META, "run": pubchem_synonyms.run, "group": "chemistry", "min_interval_days": 30},
    "chembl": {**chembl.META, "run": chembl.run, "group": "molecules", "min_interval_days": 7},
    "patent_families": {**patent_families.META, "run": patent_families.run, "group": "molecules", "min_interval_days": 7},
    "fda_labels": {**fda_labels.META, "run": fda_labels.run, "group": "chemistry", "min_interval_days": 7},
    "fda_dissolution": {**fda_dissolution.META, "run": fda_dissolution.run, "group": "chemistry", "min_interval_days": 7},
    "edqm_kd": {**edqm_kd.META, "run": edqm_kd.run, "group": "molecules", "min_interval_days": 7},
    "ph_int": {**ph_int.META, "run": ph_int.run, "group": "chemistry", "min_interval_days": 7},
    "jp": {**jp.META, "run": jp.run, "group": "chemistry", "min_interval_days": 7},
    "cdsco_plants": {**cdsco_plants.META, "run": cdsco_plants.run, "group": "sites", "min_interval_days": 7, "healthy": cdsco_plants.healthy},
    "cdsco_wc": {**cdsco_wc.META, "run": cdsco_wc.run, "group": "sites", "min_interval_days": 3},
    "eudragmdp": {**eudragmdp.META, "run": eudragmdp.run, "group": "sites", "min_interval_days": 7},
    "fda_establishments": {**fda_sites.DECRS, "run": fda_sites.run_establishments, "group": "sites", "min_interval_days": 3},
    "fda_import_alerts": {**fda_sites.IMPORT_ALERT, "run": fda_sites.run_import_alerts, "group": "sites"},
    "fda_recalls": {**fda_sites.RECALLS, "run": fda_sites.run_recalls, "group": "sites"},
    "fda_inspections": {**fda_inspections.META, "run": fda_inspections.run, "group": "sites", "min_interval_days": 7},
    "fda_dmf": {**api_filings.DMF, "run": api_filings.run_dmf, "group": "molecules", "min_interval_days": 30},
    "edqm_cep": {**api_filings.CEP, "run": api_filings.run_cep, "group": "molecules", "min_interval_days": 7},
    "ord": {**ord.META, "run": ord.run, "group": "chemistry", "min_interval_days": 30},
    "nfhs": {**health_signals.NFHS, "run": health_signals.run_nfhs, "group": "demand"},
    "idsp": {**health_signals.IDSP, "run": health_signals.run_idsp, "group": "demand", "min_interval_days": 3},
    "comtrade": {**health_signals.COMTRADE, "run": health_signals.run_comtrade, "group": "demand", "min_interval_days": 30},
}


def public_meta() -> dict[str, dict[str, Any]]:
    out = {k: {kk: vv for kk, vv in v.items() if not callable(vv)} for k, v in SOURCES.items()}
    out["cdsco"] = {**CDSCO_META, "group": "alerts"}
    return out


__all__ = ["SOURCES", "Ctx", "public_meta"]
