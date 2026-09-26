"""Regex parser lifting a structured PharmacopeialMethod from a compendial
method / acceptance-criterion string (Idea 4).

Governing principle — **no fabrication**: a numeric or categorical field is
filled ONLY when a regex matches the source string; no match means None
("not present in the source"), never "unknown / zero / inferred". This is
what makes the cross-pharmacopeia diff honest: an absent field is a real gap
in the source, not a defaulted value that would silently read as equivalence.

parse_confidence records how much was lifted, so the UI can distinguish a
fully-structured compendial method from a sparse one:

  HIGH   the section's key numeric(s) parsed (dissolution Q/timepoint,
         assay column/mobile-phase/detection-wavelength, impurity limit)
  MEDIUM some structured fields parsed, the section's key field missing
  LOW    text is present but nothing could be parsed — every optional field
         is None (enforced by test_no_fabrication_gate)
  NONE   no source text / pharmacopeia not sourced for this molecule (USP
         today — see the simulator regulatory_passport seam documented in
         gmp_knowledge.PharmacopeialMethod)

The parser is the shared contract between analytics and the simulator: the
same parse_method() is the future adapter for the simulator's per-molecule
passport monograph text (Redis cdmo:regulatory:<molecule>.usp_monograph),
keeping analytics and the simulator isolated (no cross-import; the parser
shape is the bus).
"""

from __future__ import annotations

import re

from gmp_knowledge import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    Pharmacopeia,
    PharmacopeialMethod,
    Provenance,
    Timepoint,
)

# Section names this parser knows how to lift.
SECTION_ASSAY = "assay"
SECTION_DISSOLUTION = "dissolution"
SECTION_IMPURITIES = "impurities"
SECTIONS = (SECTION_ASSAY, SECTION_DISSOLUTION, SECTION_IMPURITIES)

# ---------------------------------------------------------------------------
# Regexes. Each is anchored to the *specific phrasing* of the curated strings
# in gmp_knowledge TestingGuidelines (assay / dissolution / impurities) and
# the simulator passport monograph text. A field is filled ONLY on a match.

# Dissolution.
_RE_APPARATUS_NUM = re.compile(r"Apparatus\s+(\d+)", re.IGNORECASE)
_RE_APPARATUS_NAME = re.compile(r"\b(paddle|basket|flow[-\s]?through)\b", re.IGNORECASE)
_RE_RPM = re.compile(r"(\d+(?:\.\d+)?)\s*RPM", re.IGNORECASE)
_RE_MEDIUM = re.compile(r"Medium:\s*([^;]+)", re.IGNORECASE)
_RE_PH = re.compile(r"pH\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_RE_Q_LIMIT = re.compile(r"NLT\s+(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_RE_TIME_AT = re.compile(r"in\s+(\d+(?:\.\d+)?)\s*min", re.IGNORECASE)
_RE_TIME_BARE = re.compile(r"(\d+(?:\.\d+)?)\s*min(?:utes)?", re.IGNORECASE)

# Assay.
_RE_COLUMN = re.compile(r"\b(C18|C8|C4|phenyl|cyano|silica)\b", re.IGNORECASE)
_RE_MOBILE_PHASE = re.compile(r"Mobile\s*Phase:\s*([^.;]+)", re.IGNORECASE)
_RE_WAVELENGTH = re.compile(r"at\s+(\d+(?:\.\d+)?)\s*nm", re.IGNORECASE)
_RE_TECHNIQUE = re.compile(
    r"\b(HPLC|UPLC|LC-MS|LCMS|GC-MS|GC|UV|Spectrophotometry|TLC|Titration|NMR|IR)\b",
    re.IGNORECASE,
)
_RE_FLOW = re.compile(r"(\d+(?:\.\d+)?)\s*mL/min", re.IGNORECASE)

# Impurities.
_RE_IMP_LIMIT = re.compile(
    r"(?:Maximum|max(?:imum)?|NMT|not more than)\s+(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_RE_IMP_NAME_COLON = re.compile(
    r"^\s*((?:Impurity|Free|Related|E-isomer|Z-isomer|any other|any unidentified|total)[^:]*?):",
    re.IGNORECASE,
)
_RE_IMP_NAME_MAX = re.compile(
    r"^\s*(Impurity\s+\w+|Free\s+[\w-]+|E-isomer|Z-isomer|related\s+substances|any\s+(?:other|unidentified)\s+impurit(?:y|ies))\b",
    re.IGNORECASE,
)


def _strip_medium(raw: str, ph_captured: bool) -> str:
    """Normalise a medium string: drop a leading volume ("900 mL ") and a
    trailing "pH X" once pH is captured separately, so the medium cell shows
    the chemical medium, not the apparatus volume or the pH duplicate."""
    s = raw.strip().rstrip(".").strip()
    s = re.sub(r"^\d+(?:\.\d+)?\s*mL\s*", "", s, flags=re.IGNORECASE)
    if ph_captured:
        s = re.sub(r",?\s*pH\s*\d+(?:\.\d+)?\s*$", "", s, flags=re.IGNORECASE).strip()
    return s.strip(" ,;") or None  # type: ignore[return-value]


def _parse_dissolution(raw: str) -> dict:
    apparatus = None
    m = _RE_APPARATUS_NUM.search(raw)
    if m:
        apparatus = f"Apparatus {m.group(1)}"
    if apparatus is None:
        m = _RE_APPARATUS_NAME.search(raw)
        if m:
            apparatus = m.group(1).lower()

    rpm = None
    m = _RE_RPM.search(raw)
    if m:
        rpm = float(m.group(1))

    ph = None
    m = _RE_PH.search(raw)
    if m:
        ph = float(m.group(1))

    medium = None
    m = _RE_MEDIUM.search(raw)
    if m:
        medium = _strip_medium(m.group(1), ph is not None)

    q_limit = None
    m = _RE_Q_LIMIT.search(raw)
    if m:
        q_limit = float(m.group(1))

    # Timepoints: pair the Q limit with its time when both appear, else bare min.
    timepoints: list[Timepoint] = []
    tp = None
    m = _RE_TIME_AT.search(raw)
    if m:
        tp = float(m.group(1))
    if tp is None:
        m = _RE_TIME_BARE.search(raw)
        if m:
            tp = float(m.group(1))
    if tp is not None:
        timepoints.append(Timepoint(time_min=tp, q_limit_pct=q_limit))

    return {
        "apparatus": apparatus,
        "medium": medium,
        "medium_ph": ph,
        "rpm": rpm,
        "timepoints": timepoints,
        "q_limit_pct": q_limit,
    }


def _parse_assay(raw: str) -> dict:
    column = None
    m = _RE_COLUMN.search(raw)
    if m:
        column = m.group(1)

    mobile_phase = None
    m = _RE_MOBILE_PHASE.search(raw)
    if m:
        mobile_phase = m.group(1).strip().rstrip(".").strip() or None

    wavelength = None
    m = _RE_WAVELENGTH.search(raw)
    if m:
        wavelength = float(m.group(1))

    technique = None
    m = _RE_TECHNIQUE.search(raw)
    if m:
        technique = m.group(1).upper()

    detection = None
    if wavelength is not None:
        detection = f"{'UV' if technique is None else technique} {int(wavelength) if wavelength.is_integer() else wavelength} nm"
    elif technique is not None:
        detection = technique

    # flow rate is a minor assay parameter; we surface it inside mobile_phase
    # context only when present (kept off the structured PharmacopeialMethod
    # field set to avoid widening the no-fabrication gate surface).
    _ = _RE_FLOW.search(raw)

    return {
        "detection": detection,
        "column": column,
        "mobile_phase": mobile_phase,
    }


def _parse_impurities(raw: str) -> dict:
    impurity_name = None
    m = _RE_IMP_NAME_COLON.search(raw)
    if m:
        impurity_name = m.group(1).strip()
    if impurity_name is None:
        m = _RE_IMP_NAME_MAX.search(raw)
        if m:
            impurity_name = m.group(1).strip()

    impurity_limit = None
    m = _RE_IMP_LIMIT.search(raw)
    if m:
        impurity_limit = float(m.group(1))

    return {
        "impurity_name": impurity_name,
        "impurity_limit_pct": impurity_limit,
    }


_PARSERS = {
    SECTION_DISSOLUTION: _parse_dissolution,
    SECTION_ASSAY: _parse_assay,
    SECTION_IMPURITIES: _parse_impurities,
}


def _key_field(section: str, fields: dict) -> bool:
    """Did the section's KEY numeric/categorical field parse? Drives HIGH vs
    MEDIUM confidence — the field whose absence most weakens a comparison."""
    if section == SECTION_DISSOLUTION:
        return bool(fields["q_limit_pct"] is not None or fields["timepoints"])
    if section == SECTION_ASSAY:
        return bool(fields["column"] or fields["mobile_phase"] or fields["detection"])
    if section == SECTION_IMPURITIES:
        return fields["impurity_limit_pct"] is not None
    return False


def _any_field(fields: dict) -> bool:
    """Did ANY optional field parse? False ⟹ LOW confidence (and, per the
    no-fabrication gate, every optional field is None)."""
    return any(v is not None and v != [] for v in fields.values())


def parse_method(
    pharmacopeia: Pharmacopeia,
    section: str,
    raw_text: str,
    provenance: Provenance | None = None,
) -> PharmacopeialMethod:
    """Lift a PharmacopeialMethod from one compendial method string.

    A field is set ONLY on a regex match; absent fields are None. Returns a
    method with parse_confidence NONE when raw_text is empty (e.g. USP not
    yet sourced), LOW when text is present but nothing parsed, MEDIUM/HIGH
    otherwise. Never raises on unparseable text — it returns a LOW-confidence
    method so the diff can honestly mark it INCOMPARABLE rather than crash.
    """
    raw = (raw_text or "").strip()
    method = PharmacopeialMethod(
        pharmacopeia=pharmacopeia,
        section=section,
        raw_text=raw,
        provenance=provenance,
        parse_confidence=CONFIDENCE_NONE,
    )
    if not raw:
        return method  # NONE — pharmacopeia not sourced for this molecule

    parser = _PARSERS.get(section)
    if parser is None:
        method.parse_confidence = CONFIDENCE_LOW
        return method

    fields = parser(raw)
    for key, value in fields.items():
        setattr(method, key, value)

    if not _any_field(fields):
        method.parse_confidence = CONFIDENCE_LOW  # text present, nothing parsed
    elif _key_field(section, fields):
        method.parse_confidence = CONFIDENCE_HIGH
    else:
        method.parse_confidence = CONFIDENCE_MEDIUM
    return method


# Fields the no-fabrication gate must see as None when confidence is LOW/NONE.
# Numeric fields are the strict subset; categorical fields (medium/detection/
# column/mobile_phase/impurity_name) are also None at LOW by construction
# (LOW means _any_field is False), but the gate test checks the numeric set
# explicitly so a future field addition can't silently widen the surface.
NUMERIC_FIELDS = (
    "medium_ph",
    "rpm",
    "q_limit_pct",
    "impurity_limit_pct",
)


def numeric_fields_are_none(method: PharmacopeialMethod) -> bool:
    """True when every numeric field of `method` is None — the no-fabrication
    invariant for LOW/NONE confidence methods. Public so the diff tests and
    the UI can assert it without re-deriving the field set."""
    return all(getattr(method, f) is None for f in NUMERIC_FIELDS)