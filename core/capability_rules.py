"""Plant capabilities implied by what CDSCO lists a plant as permitted to make.

Input: the parsed CDSCO registry capabilities of one plant (dosage forms, segregated
blocks, sterile / API flags, licence classes, WHO-GMP status). Output: capability-catalog
tokens, each with a basis and the reason:

    required  Schedule M (Drugs Rules 1945, revised 2023) or WHO-GMP requires it for
              the products the plant is licensed / certified to make. A plant making
              those products lawfully has it — but this is still not an inspection record.
    inferred  usual for that dosage form, not mandatory (e.g. film coating for tablets).

Only public, rule-based facts are used. Anything that depends on the specific equipment
(bioreactor type, MES brand, Biacore...) is never derived here; it has to be stated by
a source or by the organisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import capability_catalog

INJECTABLE = {"svp_liquid", "svp_dry_powder", "lyophilised", "lvp", "prefilled_syringe"}
STERILE = INJECTABLE | {"ophthalmic"}
ORAL_SOLID = {"tablet", "capsule_hard", "capsule_soft", "dry_syrup", "oral_powder", "lozenge"}
FINISHED = ORAL_SOLID | STERILE | {"oral_liquid", "topical", "otic_nasal", "transdermal", "suppository", "inhalation",
                                   "biological", "finished_unspecified", "oral_film_gum"}
POTENT = {"cytotoxic", "hormone", "steroid", "immunosuppressant", "potent_other"}
BETA = {"beta_lactam", "cephalosporin", "carbapenem"}
LICENSED = {"manufacture", "schedule_c", "loan_licence", "loan_licence_schedule_c", "schedule_x", "lvp_sera_vaccines", "blood_products"}

# tokens outside the 7-section catalog that the scorer and seeded plants already use
EXTRA_TOKENS = {"lyophilization", "liquid_oral_filling", "sterile_liquid", "aseptic_fill"}


@dataclass(frozen=True)
class Rule:
    id: str
    when: Callable[[dict[str, Any]], bool]
    required: tuple[str, ...]
    inferred: tuple[str, ...]
    why: str


def _forms(c: dict[str, Any]) -> set[str]:
    return set(c.get("dosage_forms") or [])


def _seg(c: dict[str, Any]) -> set[str]:
    return set((c.get("segregated") or {}).keys())


RULES: list[Rule] = [
    Rule("gmp_core", lambda c: bool(_forms(c) & FINISHED) or bool(c.get("who_gmp")) or bool(set(c.get("licence_classes") or []) & LICENSED),
         ("qms", "process_validation", "validated_cleaning", "analytical_qc", "method_validation", "stability_testing",
          "controlled_room_temperature", "purified_water_generation"),
         ("edms", "compressed_air", "ftir"),
         "Schedule M: every licensed plant runs a quality system, validates processes, cleaning and test methods, "
         "keeps a stability programme, controlled storage and a purified-water system."),
    Rule("export_barcoding", lambda c: bool(c.get("who_gmp")),
         ("serialization",), ("track_and_trace", "serialization_aggregation"),
         "WHO-GMP certification is for export (COPP); DGFT requires barcodes on exported drug packs, "
         "with parent-child aggregation for tertiary packs."),
    Rule("tablet", lambda c: "tablet" in _forms(c),
         ("compression", "dissolution_testing"), ("wet_granulation", "fluid_bed_drying", "film_coating", "blister_packing"),
         "Tablets are made on a tablet press and most IP / USP tablet monographs set a dissolution test; "
         "granulation, coating and blister packing are usual but not mandatory."),
    Rule("capsule", lambda c: bool(_forms(c) & {"capsule_hard", "capsule_soft"}),
         ("dissolution_testing",), ("blister_packing", "bottle_packing"),
         "Capsule monographs set dissolution tests; strip / blister or bottle packing is usual."),
    Rule("dry_syrup_powder", lambda c: bool(_forms(c) & {"dry_syrup", "oral_powder"}),
         ("bottle_packing",), ("dry_granulation",),
         "Dry syrups are filled into bottles; sachets and powders are often dry-granulated."),
    Rule("oral_liquid", lambda c: "oral_liquid" in _forms(c),
         ("purified_water_generation", "liquid_oral_filling", "bottle_packing"), (),
         "Schedule M (oral liquids): purified water for manufacture, a liquid filling line and bottle packing."),
    Rule("topical", lambda c: bool(_forms(c) & {"topical", "transdermal", "suppository"}),
         ("purified_water_generation",), (),
         "Schedule M (external preparations): purified water for manufacture and cleaning."),
    Rule("sterile_area", lambda c: bool(_forms(c) & STERILE),
         ("grade_a_cleanroom", "grade_c_cleanroom", "positive_pressure_hvac", "hepa_terminal_filtration",
          "personnel_airlock", "material_airlock", "sterility_testing", "sterile_liquid"),
         ("clean_steam_generator", "particulate_testing"),
         "Schedule M Part 1A / WHO TRS 961 Annex 6: sterile products are filled in Grade A zones with a Grade B/C "
         "background, HEPA-filtered positive-pressure air and airlocks, and every batch is sterility-tested."),
    Rule("injectable", lambda c: bool(_forms(c) & INJECTABLE),
         ("wfi_generation", "endotoxin_testing", "particulate_testing", "visual_inspection"),
         ("clean_steam_generator", "depyrogenation_tunnel", "vial_filling"),
         "Injectables: water for injection, bacterial-endotoxin and particulate-matter tests and 100% visual "
         "inspection are pharmacopoeial / Schedule M requirements."),
    Rule("aseptic_dry", lambda c: bool(_forms(c) & {"svp_dry_powder", "lyophilised"}),
         ("aseptic_fill", "vial_filling"), ("depyrogenation_tunnel", "isolator_technology"),
         "Dry-powder and freeze-dried injectables cannot be terminally sterilised: they are filled aseptically into vials."),
    Rule("lyophilised", lambda c: "lyophilised" in _forms(c),
         ("lyophilization",), (),
         "CDSCO lists lyophilised products: the plant runs freeze-dryers."),
    Rule("prefilled_syringe", lambda c: "prefilled_syringe" in _forms(c),
         ("pfs_filling",), ("aseptic_fill",),
         "CDSCO lists pre-filled syringes / cartridges."),
    Rule("svp_liquid", lambda c: "svp_liquid" in _forms(c),
         (), ("aseptic_fill", "vial_filling"),
         "Small-volume liquid injectables are filled into ampoules or vials, aseptically or with terminal sterilisation."),
    Rule("biological", lambda c: "biological" in _forms(c),
         ("cold_room",), ("bioassay", "cold_chain_packaging", "temperature_monitored_dock"),
         "Biologicals and vaccines are stored at 2–8 °C (Schedule C / C(1)); potency is usually a bioassay."),
    Rule("beta_lactam_block", lambda c: bool(_seg(c) & BETA),
         ("building_in_building_segregation", "dedicated_equipment"), ("negative_pressure_hvac", "dust_extraction"),
         "Schedule M: penicillins, cephalosporins and carbapenems are made in dedicated, self-contained areas with "
         "separate air handling and equipment."),
    Rule("potent_block", lambda c: bool(_seg(c) & POTENT),
         ("building_in_building_segregation", "dedicated_equipment", "potent_containment"),
         ("hepa_bibo_exhaust", "high_containment_isolator", "hpapi_neutralization", "hpapi_secure_vault", "dust_extraction"),
         "Schedule M: hormones, cytotoxics and other highly active products need dedicated, segregated facilities with "
         "containment; exhaust filtration and waste deactivation are usual."),
    Rule("potent_osd", lambda c: bool(_seg(c) & POTENT) and bool(_forms(c) & {"tablet", "capsule_hard", "capsule_soft"}),
         (), ("high_containment_tablet_press", "containment_capsule_filler", "split_butterfly_valve", "vacuum_powder_transfer"),
         "Potent tablets / capsules are usually pressed and filled with contained equipment."),
    Rule("api", lambda c: bool(c.get("api")),
         (), ("solvent_recovery", "inert_gases", "gc_ms", "xrpd"),
         "API plants usually recover solvents, use nitrogen blanketing and test residual solvents (GC) and polymorphs (XRPD)."),
]

_VALID = set(capability_catalog.CAPABILITY_BY_TOKEN) | EXTRA_TOKENS


def derive(caps: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """token -> {"basis": "required" | "inferred", "why": [reasons]} for one registry plant.

    `caps` is a registry plant's capabilities dict (or its brief) plus `who_gmp`.
    """
    out: dict[str, dict[str, Any]] = {}
    for r in RULES:
        if not r.when(caps):
            continue
        for basis, toks in (("required", r.required), ("inferred", r.inferred)):
            for t in toks:
                if t not in _VALID:
                    continue
                e = out.setdefault(t, {"basis": basis, "why": []})
                if basis == "required":
                    e["basis"] = "required"
                if r.why not in e["why"]:
                    e["why"].append(r.why)
    return out


def containment(caps: dict[str, Any]) -> str:
    seg = _seg(caps)
    if "cytotoxic" in seg:
        return "cytotoxic"
    if seg & POTENT:
        return "potent"
    if "biological" in _forms(caps):
        return "biologic_GMP"
    return "standard"


APPROVED_FORMS: dict[str, list[str]] = {
    "tablet": ["solid_oral", "tablet"], "capsule_hard": ["solid_oral", "capsule"], "capsule_soft": ["solid_oral", "capsule", "softgel"],
    "oral_liquid": ["syrup", "suspension"], "dry_syrup": ["dry_syrup"], "oral_powder": ["powder"],
    "svp_liquid": ["injection", "vial"], "svp_dry_powder": ["injection", "vial", "dry_powder_injection"],
    "lyophilised": ["lyophilized_vial"], "lvp": ["lvp"], "prefilled_syringe": ["prefilled_syringe", "cartridge"],
    "ophthalmic": ["ophthalmic"], "topical": ["topical"], "inhalation": ["inhalation"], "api": ["api"], "biological": ["biologic"],
    "otic_nasal": ["drops"], "transdermal": ["transdermal"], "suppository": ["suppository"],
}


def approved_forms(caps: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for f in caps.get("dosage_forms") or []:
        for x in APPROVED_FORMS.get(f, []):
            if x not in out:
                out.append(x)
    return out


# --------------------------------------------------------------------------- EU GMP certificate scope

# Union format for GMP certificates (Part 2) -> (registry dosage forms, catalog tokens stated by the certificate).
# Longest matching code prefix wins for forms; tokens accumulate over every prefix that matches.
EU_SCOPE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "1.1": ((), ("sterile_liquid",)),
    "1.1.1": ((), ("aseptic_fill", "grade_a_cleanroom")),
    "1.1.1.1": (("lvp",), ()),
    "1.1.1.2": (("lyophilised",), ("lyophilization", "vial_filling")),
    "1.1.1.3": (("ophthalmic",), ()),
    "1.1.1.4": (("svp_liquid",), ()),
    "1.1.1.5": (("svp_dry_powder",), ()),
    "1.1.2.1": (("lvp",), ()),
    "1.1.2.2": (("topical",), ()),
    "1.1.2.3": (("svp_liquid",), ()),
    "1.1.2.4": (("svp_dry_powder",), ()),
    "1.2.1.1": (("capsule_hard",), ()),
    "1.2.1.2": (("capsule_soft",), ()),
    "1.2.1.3": (("oral_film_gum",), ()),
    "1.2.1.5": (("topical",), ()),
    "1.2.1.6": (("oral_liquid",), ("liquid_oral_filling",)),
    "1.2.1.8": (("oral_powder",), ()),
    "1.2.1.9": (("inhalation",), ()),
    "1.2.1.11": (("topical",), ()),
    "1.2.1.12": (("suppository",), ()),
    "1.2.1.13": (("tablet",), ("compression",)),
    "1.2.1.14": (("transdermal",), ()),
    "1.3": (("biological",), ()),
    "1.6.1": ((), ("sterility_testing",)),
    "1.6.2": ((), ("analytical_qc",)),
    "1.6.3": ((), ("analytical_qc",)),
    "1.6.4": ((), ("bioassay",)),
    "3.1": (("api",), ()),
    "3.2": (("api",), ()),
    "3.3": (("api",), ()),
    "3.3.2": ((), ("cell_culture",)),
    "3.4.1": ((), ("aseptic_fill",)),
    "3.6.1": ((), ("analytical_qc",)),
    "3.6.3": ((), ("sterility_testing",)),
    "3.6.4": ((), ("bioassay",)),
}
# "Other: …" entries (1.1.1.6, 1.2.1.17, 1.5.1.17) are free text
EU_OTHER = [(r"dry powder|powder for (injection|solution)", "svp_dry_powder"), (r"pre-?filled|cartridge", "prefilled_syringe"),
            (r"sachet|granule|powder", "oral_powder"), (r"implant", "svp_dry_powder"), (r"eye|ophthalm", "ophthalmic"),
            (r"inhal|nebul|respul", "inhalation"), (r"liquid|solution|syrup|suspension", "oral_liquid")]


def from_eu_scope(scope: list[dict[str, Any]]) -> tuple[set[str], dict[str, list[str]]]:
    """(dosage forms, token -> [scope lines stating it]) from an EudraGMDP site's certificate scope."""
    import re

    forms: set[str] = set()
    toks: dict[str, list[str]] = {}
    for s in scope:
        code = s["code"]
        text = f"{code} {s['label']}" + (f": {', '.join(s['details'])}" if s.get("details") else "")
        parts = code.split(".")
        prefixes = [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
        best = max((p for p in prefixes if p in EU_SCOPE and EU_SCOPE[p][0]), key=len, default=None)
        if best and code.count(".") >= best.count("."):
            forms.update(EU_SCOPE[best][0])
        for p in prefixes:
            for t in (EU_SCOPE.get(p) or ((), ()))[1]:
                if t in _VALID:
                    toks.setdefault(t, [])
                    if text not in toks[t]:
                        toks[t].append(text)
        if s["label"].lower().startswith("other") and code.startswith(("1.1.1.6", "1.1.2.5", "1.2.1.17", "1.2.1.8")):
            for pat, f in EU_OTHER:
                if re.search(pat, " ".join(s.get("details") or []).lower()):
                    forms.add(f)
                    break
    return forms, toks
