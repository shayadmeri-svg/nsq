"""Adverse-event signals from FDA's FAERS database (openFDA drug/event API).

For a molecule it counts the reactions most reported with it and scores each
with standard disproportionality measures against all FAERS reports:

    a = reports with this drug and this reaction     b = this drug, other reactions
    c = other drugs, this reaction                    d = other drugs, other reactions
    PRR = [a/(a+b)] / [c/(c+d)]
    ROR = (a/b) / (c/d), 95% CI = exp(ln ROR ± 1.96·sqrt(1/a + 1/b + 1/c + 1/d))

A signal follows Evans et al. (2001): PRR ≥ 2, chi-squared ≥ 4 and a ≥ 3.
FAERS is spontaneous reporting: counts reflect reporting, not incidence, and a
signal is a hypothesis, not proof of causation.
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

import requests

API = "https://api.fda.gov/drug/event.json"
TIMEOUT = 15
_cache: dict[str, tuple[float, Any]] = {}
TTL = 24 * 3600


def _get(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    r = requests.get(API, params=params, timeout=TIMEOUT, headers={"User-Agent": "nsq-platform/2.0 (safety signals)"})
    if r.status_code == 404:  # openFDA answers 404 for "no matches"
        return None
    r.raise_for_status()
    return r.json()


def _total(search: Optional[str] = None) -> int:
    d = _get({"search": search, "limit": 1} if search else {"limit": 1})
    return int(((d or {}).get("meta") or {}).get("results", {}).get("total") or 0)


def _counts(search: str, field: str, limit: int) -> list[dict[str, Any]]:
    d = _get({"search": search, "count": field, "limit": limit})
    return (d or {}).get("results") or []


def disproportionality(a: int, drug_total: int, reaction_total: int, all_total: int) -> dict[str, Any]:
    b = max(drug_total - a, 0)
    c = max(reaction_total - a, 0)
    d = max(all_total - drug_total - c, 0)
    if min(a, b, c, d) <= 0:
        return {"prr": None, "ror": None, "ror_low": None, "ror_high": None, "chi2": None, "signal": False}
    prr = (a / (a + b)) / (c / (c + d))
    ror = (a / b) / (c / d)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    n = a + b + c + d
    exp_a = (a + b) * (a + c) / n
    # Yates-corrected chi-squared on the 2x2 table
    chi2 = n * (abs(a * d - b * c) - n / 2) ** 2 / ((a + b) * (c + d) * (a + c) * (b + d))
    return {"prr": round(prr, 2), "ror": round(ror, 2), "ror_low": round(math.exp(math.log(ror) - 1.96 * se), 2),
            "ror_high": round(math.exp(math.log(ror) + 1.96 * se), 2), "chi2": round(chi2, 1), "expected": round(exp_a, 1),
            "signal": prr >= 2 and chi2 >= 4 and a >= 3}


def signals(name: str, top: int = 25) -> dict[str, Any]:
    key = f"{name.lower()}:{top}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    term = name.upper().replace('"', "")
    drug_q = f'patient.drug.openfda.generic_name:"{term}"'
    drug_total = _total(drug_q)
    if not drug_total:
        out = {"name": name, "found": False, "reports": 0,
               "note": "No FAERS reports under this generic name (common for medicines not sold in the US)."}
        _cache[key] = (time.time(), out)
        return out
    all_total = _total()
    rows = []
    for r in _counts(drug_q, "patient.reaction.reactionmeddrapt.exact", top):
        term_r = r["term"]
        rt = _total(f'patient.reaction.reactionmeddrapt.exact:"{term_r}"')
        rows.append({"reaction": term_r.title(), "reports": int(r["count"]), "reaction_total": rt,
                     **disproportionality(int(r["count"]), drug_total, rt, all_total)})
    serious = _total(f"{drug_q} AND serious:1")
    outcomes = {int(x["term"]): int(x["count"]) for x in _counts(drug_q, "patient.reaction.reactionoutcome", 10)}
    makers = [{"name": x["term"], "count": int(x["count"])} for x in _counts(drug_q, "patient.drug.openfda.manufacturer_name.exact", 15)]
    rows.sort(key=lambda x: (not x["signal"], -(x["prr"] or 0)))
    out = {"name": name, "found": True, "reports": drug_total, "all_reports": all_total, "serious": serious,
           "serious_pct": round(100 * serious / drug_total, 1) if drug_total else 0.0,
           "fatal": outcomes.get(5, 0), "reactions": rows, "signals": sum(1 for x in rows if x["signal"]),
           "manufacturers": makers,
           "method": "PRR / ROR against all FAERS reports; signal = PRR ≥ 2, χ² ≥ 4, n ≥ 3 (Evans 2001)",
           "caveat": "Spontaneous reports: counts reflect reporting, not how often it happens, and a signal is not proof of causation."}
    _cache[key] = (time.time(), out)
    return out
