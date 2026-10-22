"""How much of the tracked molecule set each official source covers, and what it fails to map.

Every source fetcher resolves its names through core/identity.py and stores the result as "coverage" in its file:
how many of its entries map to a tracked molecule and by which method, the names that map to none, and which tracked
molecules it covers. This puts those side by side with the limits chain (app/limits.py), molecule by molecule.
"""

from __future__ import annotations

from typing import Any

from . import limits, signals

# official documents, in the order the limits chain reads them
SOURCES = [
    ("ip", "Indian Pharmacopoeia", "limits"),
    ("ph_int", "International Pharmacopoeia (WHO)", "limits"),
    ("jp", "Japanese Pharmacopoeia (MHLW)", "limits"),
    ("fda_dissolution", "FDA Dissolution Methods Database", "method"),
    ("edqm_kd", "European Pharmacopoeia (EDQM Knowledge Database)", "monograph"),
]


def report() -> dict[str, Any]:
    import identity  # core/

    from .config import settings

    resolver = identity.load(settings.data_dir)
    sources = []
    for sid, label, gives in SOURCES:
        f = signals._load(sid)
        cov = f.get("coverage") or {}
        sources.append({"id": sid, "label": label, "gives": gives, "loaded": bool(f), "retrieved_at": f.get("retrieved_at"),
                        "entries": cov.get("entries"), "mapped": cov.get("mapped"), "by_method": cov.get("by_method") or {},
                        "unmapped": cov.get("unmapped") or [], "tracked_covered": len(cov.get("tracked_covered") or []),
                        "tracked_missing": cov.get("tracked_missing") or [], "note": cov.get("note")})
    have = {s["id"]: set((signals._load(s["id"]).get("coverage") or {}).get("tracked_covered") or []) for s in sources}
    molecules = []
    for key in sorted(resolver.keys):
        lim = limits.resolve(key)
        f = lim["fields"]
        molecules.append({"key": key, "sources": [s["id"] for s in sources if key in have[s["id"]]],
                          "assay": f.get("assay_lo", {}).get("source", "default"), "q": f.get("q_pct", {}).get("source", "default"),
                          "method": f.get("volume_ml", {}).get("source", "default")})
    total = len(molecules)

    def share(field: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in molecules:
            out[m[field]] = out.get(m[field], 0) + 1
        return out

    return {"tracked": total, "sources": sources, "molecules": molecules,
            "limits": {"assay": share("assay"), "q": share("q"), "method": share("method")},
            "no_official_source": [m["key"] for m in molecules if not m["sources"]]}
