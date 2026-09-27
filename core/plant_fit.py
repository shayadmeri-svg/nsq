"""Plant fit for a molecule, from what the molecule's dosage form needs.

Replaces the old 4-token class hint ("small_molecule_oral" = granulation, compression,
film coating, blister packing) whenever the molecule's dosage form is known. Four parts,
100 points, each shown in the explanation:

    form          25  the plant makes / is permitted to make the molecule's dosage form
    capabilities  25  share of the capabilities that form needs (capability_rules: required
                      tokens count 1, usual ones 0.5); a capability the plant only has
                      "inferred" earns half credit
    segregation   15  the separate block the molecule needs (beta-lactam, cephalosporin,
                      cytotoxic, hormone) — full marks when none is needed
    standing      20  regulatory standing: US FDA or EU GMP 20, WHO-GMP 12, licensed only 6,
                      0 under an EU non-compliance statement, FDA OAI or import alert;
                      minus 2 per NSQ alert traced to the plant, 4 if it was this molecule (at most 10)
    track record  15  evidence the plant makes this molecule: CDSCO's listing names it or an
                      EU inspection covered its API — 15; it made the molecule but batches failed
                      NSQ — 8 (and the failures cost double in standing); the company holds a US
                      DMF / CEP for the API — 8; none known — 0

No capacity or experience points: no public source has them, so they are not scored.
"""

from __future__ import annotations

from typing import Any, Optional

import capability_rules as cr

# seeded / org plant vocabulary -> registry dosage forms
SEED_FORMS: dict[str, tuple[str, ...]] = {
    "solid_oral": ("tablet", "capsule_hard"), "tablet": ("tablet",), "film_coated_tablet": ("tablet",), "uncoated_tablet": ("tablet",),
    "enteric_tablet": ("tablet",), "capsule": ("capsule_hard",), "softgel": ("capsule_soft",), "syrup": ("oral_liquid",),
    "suspension": ("oral_liquid",), "oral_liquid": ("oral_liquid",), "dry_syrup": ("dry_syrup",), "powder": ("oral_powder",),
    "injection": ("svp_liquid",), "vial": ("svp_liquid",), "dry_powder_injection": ("svp_dry_powder",),
    "lyophilized_vial": ("lyophilised",), "lvp": ("lvp",), "prefilled_syringe": ("prefilled_syringe",), "cartridge": ("prefilled_syringe",),
    "prefilled_pen": ("prefilled_syringe",), "ophthalmic": ("ophthalmic",), "topical": ("topical",), "cream": ("topical",),
    "ointment": ("topical",), "inhalation": ("inhalation",), "api": ("api",), "biologic": ("biological",), "biologic_vial": ("biological",),
    "drops": ("otic_nasal",), "transdermal": ("transdermal",), "suppository": ("suppository",),
}
REGISTRY_FORMS = set(cr.APPROVED_FORMS) | {"finished_unspecified", "lozenge", "oral_film_gum"}
_SKIP_RULES = {"gmp_core", "export_barcoding", "api"}  # every licensed plant / not about the form
SEG_TOKEN = "segregated_"  # registry plants carry segregated_<block> tokens


def plant_forms(approved_forms: list[str]) -> set[str]:
    out: set[str] = set()
    for f in approved_forms or []:
        if f in REGISTRY_FORMS:
            out.add(f)
        out.update(SEED_FORMS.get(f, ()))
    return out


def needs(forms: list[str], segregated: list[str]) -> dict[str, float]:
    """Capability tokens a plant making these forms needs: required 1.0, usual 0.5."""
    caps = {"dosage_forms": list(forms), "segregated": {s: [] for s in segregated}}
    out: dict[str, float] = {}
    for r in cr.RULES:
        if r.id in _SKIP_RULES or not r.when(caps):
            continue
        for t in r.required:
            out[t] = 1.0
        for t in r.inferred:
            out.setdefault(t, 0.5)
    return out


def _has_block(plant: Any, block: str) -> Optional[bool]:
    caps = set(plant.capabilities or [])
    if f"{SEG_TOKEN}{block}" in caps:
        return True
    if block == "cytotoxic" and plant.containment_class == "cytotoxic":
        return True
    if block in ("hormone", "cytotoxic") and plant.containment_class == "potent" and "potent_containment" in caps:
        return True
    if any(c.startswith(SEG_TOKEN) for c in caps) or getattr(plant, "reference", {}).get("registry_plant"):
        return False  # a registry plant lists its blocks: absent means absent
    return None  # a plant profile that does not record blocks: unknown


def score(forms: list[str], segregated: list[str], plant: Any, available: set[str],
          record: Optional[dict[str, Any]] = None) -> tuple[float, dict[str, Any]]:
    """0–100 plant fit and explanation. `available` = plant_available_capabilities(plant);
    `record` = {"made": NSQ alerts for this molecule, "listed": bool, "api": bool, "filing": bool, "nsq_alerts": all alerts}."""
    record = record or {}
    have_forms = plant_forms(plant.approved_forms)
    # a registry plant's own dosage-form tokens may also sit in capabilities
    have_forms |= {c for c in plant.capabilities or [] if c in REGISTRY_FORMS}
    form_hit = sorted(set(forms) & have_forms)
    form_pts = 25.0 if form_hit else 0.0

    need = needs(forms, segregated)
    basis = plant.capability_basis or {}
    got, missing, half, have_n = 0.0, [], [], 0
    for t, w in need.items():
        if t in available:
            have_n += 1
            credit = 0.5 if basis.get(t) == "inferred" else 1.0
            got += w * credit
            if credit < 1:
                half.append(t)
        elif w == 1.0:
            missing.append(t)
    total_w = sum(need.values())
    cap_pts = 25.0 * got / total_w if total_w else (25.0 if form_hit else 0.0)

    seg_pts, seg_note = 15.0, "no separate block needed"
    warn: list[str] = []
    for b in segregated:
        h = _has_block(plant, b)
        if h is False:
            seg_pts, seg_note = 0.0, f"needs a separate {b.replace('_', '-')} block — the plant has none"
            warn.append(seg_note)
            break
        if h is None:
            seg_pts, seg_note = 7.5, f"needs a separate {b.replace('_', '-')} block — not recorded for this plant"
    certs = {c.upper() for c in plant.certifications_active or []}
    bad = [c for c in certs if c in ("EU_NCR", "FDA_OAI", "FDA_IMPORT_ALERT")]
    if bad:
        stand_pts, stand_note = 0.0, "under " + ", ".join(b.replace("_", " ") for b in bad)
        warn.append(stand_note)
    elif certs & {"USFDA", "EU_GMP", "UK_MHRA", "PICS", "TGA", "HEALTH_CANADA", "PMDA"}:
        stand_pts, stand_note = 20.0, "stringent-regulator approval: " + ", ".join(sorted(certs & {"USFDA", "EU_GMP", "UK_MHRA", "PICS", "TGA", "HEALTH_CANADA", "PMDA"}))
    elif "WHO_GMP" in certs:
        stand_pts, stand_note = 12.0, "WHO-GMP"
    else:
        stand_pts, stand_note = 6.0, "no certification on record"
    nsq, made = int(record.get("nsq_alerts") or 0), int(record.get("made") or 0)
    if nsq and stand_pts:
        cut = min(10.0, 2.0 * nsq + 2.0 * made, stand_pts)  # a failure of this very molecule counts double
        stand_pts -= cut
        stand_note += f"; −{cut:.0f} for {nsq} NSQ alert{'s' if nsq > 1 else ''}" + (f" ({made} for this molecule)" if made else "")
    if record.get("api"):
        rec_pts, rec_note = 15.0, "an EU GMP inspection covered this API here"
    elif record.get("listed"):
        rec_pts, rec_note = 15.0, "CDSCO's listing for the plant names this molecule"
    elif made:
        rec_pts, rec_note = 8.0, f"has made it — but {made} batch{'es' if made > 1 else ''} failed NSQ"
    elif record.get("filing"):
        rec_pts, rec_note = 8.0, "the company holds a US DMF / CEP for the API (site not named)"
    else:
        rec_pts, rec_note = 0.0, "no public record of it making this molecule"
    if not form_hit:
        warn.append(f"does not make the form ({', '.join(forms)})")

    total = round(form_pts + cap_pts + seg_pts + stand_pts + rec_pts, 1)
    return total, {
        "summary": f"Plant fit {total:.0f}/100 on {plant.site_name}: " + ("makes " + ", ".join(form_hit) if form_hit else "does not make " + " / ".join(forms))
                   + f"; has {have_n}/{len(need)} capabilities the form needs" + (f"; {seg_note}" if segregated else "") + f"; {stand_note}; {rec_note}.",
        "method": "dosage form",
        "parts": {"form": round(form_pts, 1), "capabilities": round(cap_pts, 1), "segregation": round(seg_pts, 1),
                  "standing": round(stand_pts, 1), "record": round(rec_pts, 1)},
        "max": {"form": 25, "capabilities": 25, "segregation": 15, "standing": 20, "record": 15},
        "molecule_forms": forms, "plant_forms": sorted(have_forms), "segregated_needed": segregated,
        "missing_capabilities": sorted(missing), "inferred_capabilities": sorted(half),
        "capability_match": f"{have_n}/{len(need)} capabilities the form needs (required ones missing: {', '.join(sorted(missing)) or 'none'})",
        "segregation": seg_note, "standing": stand_note, "record": rec_note, "warnings": warn,
    }
