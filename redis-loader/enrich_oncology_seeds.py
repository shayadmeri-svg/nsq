"""Enrich seed files for the 8 oncology molecules with the detailed table provided.

Updates data/patent_seed.json, data/regulatory_seed.json, and data/demand_seed.json
with richer thicket, compendial, analytical, scientific-context, and GMP information
from data/oncology_molecule_table.json.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATENT_PATH = ROOT / "data" / "patent_seed.json"
REGULATORY_PATH = ROOT / "data" / "regulatory_seed.json"
DEMAND_PATH = ROOT / "data" / "demand_seed.json"

ONCOLOGY_TABLE_PATH = ROOT / "data" / "oncology_molecule_table.json"


def _load_oncology_table() -> dict[str, dict]:
    """Load the 8-molecule oncology table from data/oncology_molecule_table.json.

    Returns a dict keyed by molecule_key for fast lookup.
    """
    with open(ONCOLOGY_TABLE_PATH, "r", encoding="utf-8") as f:
        table = json.load(f)
    return {entry["molecule_key"]: entry for entry in table.get("molecules", [])}


def _find_index(items: list[dict], key: str) -> int:
    for i, item in enumerate(items):
        if item.get("molecule_key") == key:
            return i
    return -1


def enrich_patents(seed: dict) -> None:
    molecules = seed["molecules"]
    for key, data in _load_oncology_table().items():
        idx = _find_index(molecules, key)
        if idx < 0:
            print(f"WARNING: {key} not found in patent_seed.json")
            continue
        entry = molecules[idx]
        entry["notes"] = (
            f"{data['brand_sponsor']}. {data['registry']}. "
            f"{data['form']} — {data['formulation_class']}. "
            f"{data['loe_horizon']}. "
            f"Thicket strategy: {data['thicket_strategy']}"
        )
        # Append thicket patents to secondary/formulation descriptions where empty
        for sec in entry.get("secondary_patents", []):
            if not sec.get("description"):
                sec["description"] = data["thicket_strategy"][:120]
        for proc in entry.get("process_patents", []):
            if not proc.get("description"):
                proc["description"] = f"{data['formulation_class']} process controls"


def enrich_regulatory(seed: dict) -> None:
    passports = seed["passports"]
    for key, data in _load_oncology_table().items():
        idx = _find_index(passports, key)
        if idx < 0:
            print(f"WARNING: {key} not found in regulatory_seed.json")
            continue
        p = passports[idx]
        p["ip_2026_monograph"] = data["compendial_standards"]
        p["ph_eur_monograph"] = data["compendial_standards"]
        p["usp_monograph"] = data["compendial_standards"]
        p["analytical_specs"] = data["testing_protocols"]
        p["stability_conditions"] = data["gmp_methodologies"]
        p["notes"] = (
            f"Scientific context: {data['scientific_context']} "
            f"| GMP / Containment / CCIT: {data['gmp_methodologies']}"
        )
        p["bioequivalence_notes"] = (
            f"{data['form']} — {data['formulation_class']}. "
            f"{data['loe_horizon']}."
        )


def enrich_demand(seed: dict) -> None:
    profiles = seed["profiles"]
    for key, data in _load_oncology_table().items():
        idx = _find_index(profiles, key)
        if idx < 0:
            print(f"WARNING: {key} not found in demand_seed.json")
            continue
        p = profiles[idx]
        p["notes"] = (
            f"{data['brand_sponsor']}; {data['formulation_class']}. "
            f"{data['loe_horizon']}. {p['notes']}"
        )


def main() -> None:
    for path, enrich_fn in [
        (PATENT_PATH, enrich_patents),
        (REGULATORY_PATH, enrich_regulatory),
        (DEMAND_PATH, enrich_demand),
    ]:
        with open(path, "r", encoding="utf-8") as f:
            seed = json.load(f)
        enrich_fn(seed)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(seed, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
