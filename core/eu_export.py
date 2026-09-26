"""EU export readiness — a molecule × plant checklist for the EU generic route.

Pure and headless (stdlib + the intelligence models). Every item names the
EU instrument it comes from, the evidence it used, and how to close the gap.
Nothing here is inferred beyond the seeds: when the seed has no data for an
item, the item says so ("attention") instead of guessing "met".

Statuses:
    met        — evidence in the seeds/plant profile satisfies the item
    attention  — cannot be confirmed from the data we hold; a human must check
    gap        — the data shows the requirement is not satisfied today
    na         — does not apply to this molecule
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

MET, ATTENTION, GAP, NA = "met", "attention", "gap", "na"


@dataclass
class ChecklistItem:
    id: str
    title: str
    status: str
    detail: str
    how_to_close: str = ""
    reference: str = ""


@dataclass
class EuAssessment:
    molecule_key: str
    api_name: str
    brand_name: str
    plant_asset_id: Optional[str]
    plant_name: Optional[str]
    eu_loe: Optional[str]
    eu_market_status: str
    eu_patent_barrier: str
    readiness_pct: int
    verdict: str
    items: list[ChecklistItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["counts"] = {s: sum(1 for i in self.items if i.status == s) for s in (MET, ATTENTION, GAP, NA)}
        return d


_STERILE_CAPS = {"aseptic_fill", "isolator_technology", "barrier_isolator_filling", "grade_a_cleanroom"}
_SERIALIZATION_CAPS = {"serialization", "serialization_aggregation", "track_and_trace"}


def _norm(values: Iterable[str]) -> set[str]:
    return {(v or "").lower().replace("-", "_").strip() for v in values}


def _eu_geo(patent) -> Optional[Any]:
    for g in getattr(patent, "geo_coverage", []) or []:
        if (g.country_code or "").upper() == "EU":
            return g
    return None


def _years_until(d: Optional[date], today: date) -> Optional[float]:
    if d is None:
        return None
    return (d - today).days / 365.25


def assess(
    patent,
    regulatory=None,
    complexity=None,
    plant=None,
    nsq_alerts_for_molecule: int = 0,
    today: Optional[date] = None,
) -> EuAssessment:
    """Build the EU export checklist for one molecule on one plant."""
    today = today or date.today()
    items: list[ChecklistItem] = []

    geo = _eu_geo(patent)
    eu_loe = (geo.loe_date if geo and geo.loe_date else None) or getattr(patent, "estimated_loe_eu", None)
    status_str = geo.market_status if geo else "unknown"
    barrier = geo.patent_barrier if geo else "unknown"
    yrs = _years_until(eu_loe, today)

    # 1. Market access: EU patent / SPC expiry.
    if (geo and geo.export_eligible) or (yrs is not None and yrs <= 0):
        items.append(ChecklistItem(
            "eu_market_open", "EU patent & SPC protection expired", MET,
            f"EU status: {status_str}; LOE {eu_loe.isoformat() if eu_loe else 'n/a'}.",
            reference="Patent / SPC register (Regulation (EC) No 469/2009)"))
    elif yrs is not None and yrs <= 3:
        items.append(ChecklistItem(
            "eu_market_open", "EU patent & SPC protection expired", ATTENTION,
            f"EU LOE in {yrs:.1f} years ({eu_loe.isoformat()}); barrier: {barrier}.",
            "Start development and bioequivalence now: the EU Bolar exemption allows studies "
            "for a generic MAA before expiry. Launch only after patent and SPC expiry.",
            "Directive 2001/83/EC Art. 10(6) (Bolar)"))
    else:
        items.append(ChecklistItem(
            "eu_market_open", "EU patent & SPC protection expired", GAP,
            f"EU LOE {eu_loe.isoformat() if eu_loe else 'unknown'}; barrier: {barrier}.",
            "Track the SPC and secondary patents; revisit when LOE is within 3 years, "
            "or pursue a non-infringing formulation/process.",
            "Regulation (EC) No 469/2009 (SPC)"))

    # 2. Pharmacopoeial standard.
    mono = (getattr(regulatory, "ph_eur_monograph", "") or "").strip() if regulatory else ""
    if mono:
        items.append(ChecklistItem(
            "ph_eur", "Ph. Eur. monograph available", MET, f"Monograph: {mono}.",
            reference="European Pharmacopoeia"))
    else:
        items.append(ChecklistItem(
            "ph_eur", "Ph. Eur. monograph available", ATTENTION,
            "No Ph. Eur. monograph recorded for this molecule.",
            "Set in-house specifications justified against Ph. Eur. general chapters and ICH Q6A/Q6B; "
            "validate methods per ICH Q2(R2).",
            "Ph. Eur. general chapters; ICH Q6A/Q6B"))

    # 3. Site GMP status.
    certs = _norm(getattr(plant, "certifications_active", []) or []) if plant else set()
    if plant is None:
        items.append(ChecklistItem(
            "eu_gmp_site", "Site holds an EU GMP certificate", GAP,
            "No plant linked to this organisation.",
            "Link or create a plant profile for the organisation.", "EudraLex Vol. 4"))
    elif "eu_gmp" in certs:
        items.append(ChecklistItem(
            "eu_gmp_site", "Site holds an EU GMP certificate", MET,
            f"{plant.site_name} lists EU GMP as active.",
            reference="EudraLex Vol. 4; EudraGMDP"))
    else:
        items.append(ChecklistItem(
            "eu_gmp_site", "Site holds an EU GMP certificate", GAP,
            f"{plant.site_name} active certifications: {', '.join(sorted(certs)) or 'none'}.",
            "Prepare for and pass an inspection by an EEA competent authority (or an MRA partner "
            "authority); the certificate is then published in EudraGMDP.",
            "EudraLex Vol. 4; Directive 2001/83/EC Art. 111"))

    # 4. Sterile manufacture (Annex 1).
    sterile = bool(getattr(complexity, "sterility_required", False)) if complexity else False
    if not sterile:
        items.append(ChecklistItem("annex_1", "Annex 1 sterile manufacturing", NA,
                                   "Non-sterile dosage form.", reference="EU GMP Annex 1 (2022)"))
    else:
        caps = _norm(getattr(plant, "capabilities", []) or []) if plant else set()
        caps |= _norm((t.get("capability") or "") for t in (getattr(plant, "equipment_trains", []) or [])) if plant else set()
        if plant and caps & _STERILE_CAPS and "eu_gmp" in certs:
            items.append(ChecklistItem(
                "annex_1", "Annex 1 sterile manufacturing", ATTENTION,
                "Aseptic capability and EU GMP present; Annex 1 (2022) compliance not recorded.",
                "Confirm a documented Contamination Control Strategy, isolator/RABS use and "
                "media-fill history against the 2022 Annex 1.",
                "EU GMP Annex 1 (2022, in force Aug 2023)"))
        else:
            items.append(ChecklistItem(
                "annex_1", "Annex 1 sterile manufacturing", GAP,
                "Sterile product; the plant lacks aseptic capability or EU GMP.",
                "Add grade A isolator filling and a Contamination Control Strategy; validate by media fills.",
                "EU GMP Annex 1 (2022)"))

    # 5. Bioequivalence / biosimilarity.
    modality = getattr(complexity, "modality", "small_molecule") if complexity else "small_molecule"
    be_notes = (getattr(regulatory, "bioequivalence_notes", "") or "").strip() if regulatory else ""
    if modality != "small_molecule":
        items.append(ChecklistItem(
            "similarity", "Biosimilar comparability exercise", ATTENTION,
            f"{modality.replace('_', ' ')} — generic route does not apply.",
            "Plan the quality, non-clinical and clinical comparability exercise against the EU reference product.",
            "Directive 2001/83/EC Art. 10(4); EMA biosimilar guidelines"))
    else:
        items.append(ChecklistItem(
            "similarity", "Bioequivalence vs EU reference product", ATTENTION,
            be_notes or "No bioequivalence data recorded.",
            "Run a BE study against the EU reference medicinal product (or justify a BCS biowaiver per ICH M9).",
            "CPMP/EWP/QWP/1401/98 Rev.1; ICH M9"))

    # 6. Stability for the EU climatic zone.
    stab = (getattr(regulatory, "stability_conditions", "") or "") if regulatory else ""
    if "25" in stab and "60" in stab:
        items.append(ChecklistItem("stability", "Stability data for climatic zone II", MET,
                                   f"Recorded: {stab}.", reference="ICH Q1A(R2)"))
    else:
        items.append(ChecklistItem(
            "stability", "Stability data for climatic zone II", ATTENTION,
            f"Recorded: {stab or 'none'}. India registrations typically use zone IVb (30 °C/75 % RH).",
            "Ensure long-term 25 °C/60 % RH (or covering IVb data) on commercial-scale batches.",
            "ICH Q1A(R2)"))

    # 7. Falsified Medicines Directive.
    caps_all = set()
    if plant:
        caps_all = _norm(plant.capabilities) | _norm((t.get("capability") or "") for t in plant.equipment_trains)
    if plant and caps_all & _SERIALIZATION_CAPS:
        items.append(ChecklistItem("fmd", "Serialisation & anti-tampering (FMD)", MET,
                                   "Plant lists serialisation capability.",
                                   reference="Delegated Regulation (EU) 2016/161"))
    else:
        items.append(ChecklistItem(
            "fmd", "Serialisation & anti-tampering (FMD)", GAP,
            "No serialisation capability on the plant profile.",
            "Add unique-identifier printing/verification and anti-tampering devices, connected to the EMVS hub.",
            "Delegated Regulation (EU) 2016/161"))

    # 8. EU importer / QP release.
    items.append(ChecklistItem(
        "qp_release", "EU importer with QP batch release", ATTENTION,
        "Every batch imported into the EU must be certified by a Qualified Person of an EU MIA holder.",
        "Contract an EU importer/MIA holder (or set up an EU entity) and agree a technical agreement.",
        "Directive 2001/83/EC Art. 40 & 51"))

    # 9. Active substance written confirmation.
    items.append(ChecklistItem(
        "written_confirmation", "Written confirmation for the API", ATTENTION,
        "APIs made in India and imported into the EU need a written confirmation from CDSCO "
        "(India is not on the EU equivalence list).",
        "Obtain the CDSCO written confirmation per API site, or hold an EU GMP certificate for the API site.",
        "Directive 2001/83/EC Art. 46b(2)"))

    # 10. Quality signal from CDSCO NSQ alerts.
    if nsq_alerts_for_molecule > 0:
        items.append(ChecklistItem(
            "nsq_signal", "No open quality signals on this molecule", GAP,
            f"{nsq_alerts_for_molecule} CDSCO NSQ alert(s) on this molecule for the organisation.",
            "Close root-cause investigations and CAPAs before inspection; inspectors review market quality history.",
            "EudraLex Vol. 4 Ch. 1 & 8"))
    else:
        items.append(ChecklistItem("nsq_signal", "No open quality signals on this molecule", MET,
                                   "No CDSCO NSQ alerts on this molecule for the organisation.",
                                   reference="CDSCO NSQ alerts"))

    applicable = [i for i in items if i.status != NA]
    score = sum(1.0 if i.status == MET else 0.5 if i.status == ATTENTION else 0.0 for i in applicable)
    pct = int(round(100 * score / len(applicable))) if applicable else 0
    gaps = sum(1 for i in applicable if i.status == GAP)
    verdict = "ready" if gaps == 0 and pct >= 75 else "close" if gaps <= 2 else "far"

    return EuAssessment(
        molecule_key=patent.molecule_key,
        api_name=patent.api_name,
        brand_name=patent.brand_name,
        plant_asset_id=plant.asset_id if plant else None,
        plant_name=plant.site_name if plant else None,
        eu_loe=eu_loe.isoformat() if eu_loe else None,
        eu_market_status=status_str,
        eu_patent_barrier=barrier,
        readiness_pct=pct,
        verdict=verdict,
        items=items,
    )
