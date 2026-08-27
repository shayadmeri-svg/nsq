"""Cross-pharmacopeia structured diff (Idea 4): IP 2026 vs Ph. Eur. vs USP.

Turns the per-molecule TestingGuidelines text in gmp_knowledge.PRODUCT_CATALOG
into machine-comparable PharmacopeialMethod objects, then classifies each
section's comparison across the three pharmacopeias:

  NSQ_RELEVANT     a numeric / method difference that could change a pass/fail
                   verdict or NSQ risk (different Q, timepoint, medium pH,
                   impurity limit, apparatus, technique). This is the signal
                   the analytics app exists to surface: a molecule whose
                   compendial method differs across markets is one where a
                   plant validated to one pharmacopeia can silently fail another.
  METHOD_EQUIVALENT numerically identical where both parsed (wording differs).
  INCOMPARABLE     one or both sides too sparse to compare honestly. Never
                   asserted equivalent — unproven equivalence is itself an
                   NSQ risk, so the honest classifier refuses to claim it.

No-fabrication contract: the diff operates ONLY on parsed fields. Where a
side is LOW/NONE confidence (nothing parsed), the comparison is INCOMPARABLE,
never a defaulted equivalence. This is why PharmacopeialMethod numeric
fields are None-by-default and why test_no_fabrication_gate exists.

Synergy with the simulator plant features (documented seam; analytics and
the simulator are intentionally isolated — Redis is the shared bus, no
cross-import):

  AXIS SEAM — the three Pharmacopeia members (IP2026 / PH_EUR / USP) are the
  same three axes the simulator's regulatory_passport page already tracks per
  molecule (passport.ip_2026_monograph / ph_eur_monograph / usp_monograph in
  Redis cdmo:regulatory:<molecule>). The US regulatory axis is now wired with
  REAL FDA Orange Book data (us_regulatory_data.py: TE codes, RLD, applicant,
  cited to openFDA at the regulatory_registry tier) for 16/17 molecules —
  vildagliptin is honestly absent (not FDA-approved). The USP compendial
  *method* text (apparatus/medium/limits) is subscription-gated (USP-NF), so
  diff_drug() still emits a None USP PharmacopeialMethod (NONE confidence):
  the FDA Dissolution Methods database is the identified public citable
  source for US dissolution methods to wire next — never baked uncited.

  PLANT SEAM — a plant's capability tokens (simulator capability_catalog:
  dissolution_testing, rp_uplc, gc_ms, stability_testing, method_validation,
  ...) joined with MethodDiff.significance == NSQ_RELEVANT yields a
  plant-specific pharmacopeial risk surface: a plant lacking
  `dissolution_testing` cannot serve a market whose pharmacopeia sets an
  NSQ-relevant dissolution method; a plant without `rp_uplc` cannot run the
  HPLC assay a given pharmacopeia specifies. That overlay lives in the
  simulator (consuming this diff shape via the same parser), not here.
"""

from __future__ import annotations

from gmp_knowledge import (
    DIFF_INCOMPARABLE,
    DIFF_METHOD_EQUIVALENT,
    DIFF_NSQ_RELEVANT,
    CONFIDENCE_LOW,
    CONFIDENCE_NONE,
    CoverageCell,
    Drug,
    MethodDiff,
    Pharmacopeia,
    PharmacopeialMethod,
    TestingGuidelines,
)
from pharmacopeia_methods import (
    SECTION_ASSAY,
    SECTION_DISSOLUTION,
    SECTION_IMPURITIES,
    SECTIONS,
    parse_method,
)
import ich_registry  # noqa: E402  — cited Q4B harmonisation context for the diff


# Fields compared per section for NSQ relevance. Each is a PharmacopeialMethod
# attribute name. A pairwise difference on any of these in a section flips the
# section to NSQ_RELEVANT. Only fields that actually parsed (non-None on BOTH
# sides) count — a difference between a value and None is INCOMPARABLE, not
# NSQ_RELEVANT, because we cannot assert the missing side matches or differs.
_DISSOLUTION_FIELDS = ("apparatus", "rpm", "medium_ph", "q_limit_pct")
_ASSAY_FIELDS = ("column", "detection")
_IMPURITIES_FIELDS = ("impurity_limit_pct",)

_SECTION_FIELDS = {
    SECTION_DISSOLUTION: _DISSOLUTION_FIELDS,
    SECTION_ASSAY: _ASSAY_FIELDS,
    SECTION_IMPURITIES: _IMPURITIES_FIELDS,
}

# The timepoint list is compared structurally: a different sampling time (or a
# different Q at the same time) is NSQ-relevant. Medium identity is compared
# as a normalised string but is a softer signal — captured in the rationale,
# not a hard NSQ_RELEVANT trigger on its own (a medium name difference is
# often a wording variant, e.g. "Water" vs "Water R").


def _normalise(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().lower()


def _comparable(a: PharmacopeialMethod | None, b: PharmacopeialMethod | None) -> bool:
    """Two methods are comparable iff both parsed at least something (above
    LOW/NONE confidence). A side that lifted nothing cannot be compared."""
    if a is None or b is None:
        return False
    if a.parse_confidence in (CONFIDENCE_NONE, CONFIDENCE_LOW):
        return False
    if b.parse_confidence in (CONFIDENCE_NONE, CONFIDENCE_LOW):
        return False
    return True


def _timepoints_differ(a: PharmacopeialMethod, b: PharmacopeialMethod) -> bool:
    """Different sampling time or different Q at a time, where both parsed."""
    ta = [(round(t.time_min, 2), round(t.q_limit_pct, 2) if t.q_limit_pct is not None else None)
          for t in a.timepoints]
    tb = [(round(t.time_min, 2), round(t.q_limit_pct, 2) if t.q_limit_pct is not None else None)
          for t in b.timepoints]
    if not ta or not tb:
        return False  # one side has no parsed timepoint → not a proven difference
    return ta != tb


def _classify_pair(
    section: str,
    a: PharmacopeialMethod | None,
    b: PharmacopeialMethod | None,
    label_a: str,
    label_b: str,
) -> tuple[str, str]:
    """Classify a two-way comparison (the analytics core: IP2026 vs PH_EUR;
    USP is carried but not compared until the Redis adapter lands)."""
    if not _comparable(a, b):
        if a is None and b is None:
            return DIFF_INCOMPARABLE, f"neither {label_a} nor {label_b} sourced"
        if a is None or a.parse_confidence in (CONFIDENCE_NONE, CONFIDENCE_LOW):
            return DIFF_INCOMPARABLE, f"{label_a} not parseable enough to compare"
        return DIFF_INCOMPARABLE, f"{label_b} not parseable enough to compare"

    diffs: list[str] = []
    for field in _SECTION_FIELDS.get(section, ()):
        va, vb = _normalise(getattr(a, field)), _normalise(getattr(b, field))
        if va is not None and vb is not None and va != vb:
            diffs.append(f"{field}: {label_a}={getattr(a, field)} vs {label_b}={getattr(b, field)}")
    if _timepoints_differ(a, b):
        diffs.append(
            f"timepoint/Q: {label_a}={[(t.time_min, t.q_limit_pct) for t in a.timepoints]} "
            f"vs {label_b}={[(t.time_min, t.q_limit_pct) for t in b.timepoints]}"
        )

    if diffs:
        return DIFF_NSQ_RELEVANT, "; ".join(diffs)
    return DIFF_METHOD_EQUIVALENT, f"parsed {section} numerics match where both lifted"


def _tg_method(
    pharmacopeia: Pharmacopeia,
    section: str,
    tg: TestingGuidelines | None,
) -> PharmacopeialMethod | None:
    """Build a PharmacopeialMethod from a TestingGuidelines section text, or
    None if the TestingGuidelines itself is absent."""
    if tg is None:
        return None
    raw = getattr(tg, section, "") or ""
    return parse_method(pharmacopeia, section, raw, tg.provenance)


def diff_drug(drug: Drug) -> list[MethodDiff]:
    """Build the per-section cross-pharmacopeia diff for one drug.

    IP2026 and PH_EUR are parsed from the drug's TestingGuidelines (owned by
    analytics). USP is carried as None — analytics has no USP field today; the
    simulator passport seam (see module docstring) populates it later via the
    same parser. Significance is classified IP2026-vs-PH_EUR (the two sourced
    axes); USP is surfaced in the methods dict and coverage matrix as a NONE
    cell so the citation debt is visible, never silently empty.
    """
    out: list[MethodDiff] = []
    for section in SECTIONS:
        ip = _tg_method(Pharmacopeia.IP2026, section, drug.ip2026)
        eur = _tg_method(Pharmacopeia.PH_EUR, section, drug.ph_eur)
        usp = None  # seam: load_usp_from_redis() adapter, see module docstring
        significance, rationale = _classify_pair(
            section, ip, eur, "IP 2026", "Ph. Eur."
        )
        out.append(MethodDiff(
            section=section,
            methods={Pharmacopeia.IP2026: ip, Pharmacopeia.PH_EUR: eur, Pharmacopeia.USP: usp},
            significance=significance,
            rationale=rationale,
            # ICH Q4B harmonisation scope note for this section, or None where no
            # Q4B annex applies (assay, impurities). Only dissolution maps to a
            # Q4B annex (Annex 7(R2)); the note states the honest scope boundary.
            ich_harmonisation=ich_registry.harmonisation_note(section),
        ))
    return out


def coverage_matrix(catalog: dict[str, Drug]) -> dict[str, dict[Pharmacopeia, CoverageCell]]:
    """17 x 3 molecule-by-pharmacopeia coverage matrix: for each drug, is a
    compendial method sourced (present) and at what parse depth, per
    pharmacopeia. A cell is present=True when ANY of the drug's three sections
    parsed above NONE confidence for that pharmacopeia. The USP column is
    entirely absent today (the seam) — surfaced honestly as present=False
    across all rows so the gap is auditable, not hidden."""
    matrix: dict[str, dict[Pharmacopeia, CoverageCell]] = {}
    for key, drug in catalog.items():
        diffs = diff_drug(drug)
        row: dict[Pharmacopeia, CoverageCell] = {}
        for pharm in Pharmacopeia:
            methods = [d.methods.get(pharm) for d in diffs]
            present_methods = [m for m in methods if m is not None and m.parse_confidence != CONFIDENCE_NONE]
            representative = present_methods[0] if present_methods else None
            row[pharm] = CoverageCell(
                pharmacopeia=pharm,
                present=bool(present_methods),
                method=representative,
            )
        matrix[key] = row
    return matrix


def nsq_relevant_count(drug: Drug) -> int:
    """Number of sections with an NSQ_RELEVANT IP2026-vs-PH_EUR difference —
    a one-number risk surface the UI can surface per molecule."""
    return sum(1 for d in diff_drug(drug) if d.significance == DIFF_NSQ_RELEVANT)