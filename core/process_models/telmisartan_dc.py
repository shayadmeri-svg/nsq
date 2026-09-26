"""Telmisartan manufacturing process simulator — Direct-Compression route.

This is the SECOND telmisartan route, added alongside the NaOH fluid-bed model
(`telmisartan.py`) and selected via the route registry. It is anchored to the
curated GMP corridor in analytics/shared/gmp_knowledge.py for telmisartan
(id="telmisartan", optimal_process="Direct Compression"), whose ideal_parameters
are:
    * Dry Blending Time 15-25 min (ideal 20)
    * Rotary Press Speed  20-45 RPM (ideal 32)
and whose common_alerts are:
    * Dissolution — fails NLT 75% in 45 min (pH 7.5) via meglumine crystallization
    * Description — hygroscopic liquefaction / sticking
    * Assay — sub-potency from solid-state crystal transitions

The model adds a third formulation CPP — meglumine ratio (%) — because the
catalog lists Meglumine as the alkalizer excipient (6.0%) but gives no corridor
range; 70..130% relative to the ideal is an illustrative envelope.

Two stages, mirroring the NaOH route's shape so the API/UI treat every route
identically:
    Stage 1 — Dry Blending:  blending_time_min, meglumine_ratio_pct
    Stage 2 — Tablet Compression: rotary_press_rpm  (chains on Stage 1 outputs,
             because dissolution depends on meglumine distribution AND compaction)

Everything is deterministic and side-effect-free. The illustrative rules are the
seam: a mechanistic model can replace them without touching the API or UI.
"""
from __future__ import annotations

from dataclasses import dataclass

from .telmisartan import FailureMode, Severity, _worst


# ---------------------------------------------------------------------------
# CPP inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DCStage1Params:
    """Dry-blending CPPs.

    blending_time_min matches the catalog corridor (15-25 min, ideal 20).
    meglumine_ratio_pct is relative to the ideal 6.0% alkalizer load
    (100% = ideal); too little drives meglumine crystallization and a
    dissolution shortfall, too much drives hygroscopic sticking."""

    blending_time_min: float = 20.0       # 5..40, optimum 15-25, ideal 20 (catalog)
    meglumine_ratio_pct: float = 100.0    # 70..130, target 100 (= 6.0% load)


@dataclass(frozen=True)
class DCStage2Params:
    """Tablet-compression CPP. rotary_press_rpm matches the catalog corridor
    (20-45 RPM, ideal 32). Compression force is implicit in press speed here;
    a future model may split it out."""

    rotary_press_rpm: float = 32.0        # 10..60, optimum 20-45, ideal 32 (catalog)


# ---------------------------------------------------------------------------
# CQA outputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DCStage1Result:
    content_uniformity_rsd: float   # blend uniformity RSD, % (lower is better)
    blend_potency_pct: float        # API potency proxy after blending, %
    severity: Severity
    failure_mode: FailureMode
    title: str
    description: str


@dataclass(frozen=True)
class DCStage2Result:
    tablet_hardness_kn: float       # mean tablet hardness, kN
    dissolution_pct: float          # % released at 45 min in pH 7.5 phosphate buffer
    severity: Severity
    failure_mode: FailureMode
    title: str
    description: str


# ---------------------------------------------------------------------------
# Range contracts — single source of truth, shared with API and UI.
# ---------------------------------------------------------------------------
DC_STAGE1_RANGES: dict[str, dict[str, float]] = {
    "blending_time_min":   {"min": 5, "max": 40, "optimum_low": 15, "optimum_high": 25, "step": 1},
    "meglumine_ratio_pct": {"min": 70, "max": 130, "target": 100, "step": 1},
}
DC_STAGE2_RANGES: dict[str, dict[str, float]] = {
    "rotary_press_rpm": {"min": 10, "max": 60, "optimum_low": 20, "optimum_high": 45, "step": 1},
}


# ---------------------------------------------------------------------------
# Stage 1 — dry blending
# ---------------------------------------------------------------------------
def simulate_dc_stage1(p: DCStage1Params) -> DCStage1Result:
    """Map dry-blending CPPs to CQAs + a single failure mode.

    Illustrative rules (unit-tested):
      * content_uniformity_rsd: 2.0% at blend time >= 20 min; rises linearly
        as time falls below 20 (under-blending -> poor meglumine/API
        distribution). At 15 min -> 3.5%, at 5 min -> 6.5%.
      * blend_potency_pct: 100% at full meglumine; sub-potency grows as
        meglumine drops (solid-state crystal transition risk from incomplete
        stabilization). At 70% meglumine -> 98% potency.
      * Failure precedence: under_blending (WARNING) if time < 15 — the
        catalog's Assay alert (sub-potency from under-blending). Then
        meglumine_deficit (WARNING) if meglumine < 85 — an early formulation
        flag whose downstream consequence is dissolution failure in Stage 2.
        Else OPTIMAL.
    """
    rsd = 2.0 + max(0.0, 20.0 - p.blending_time_min) * 0.3
    potency = 100.0 - max(0.0, 100.0 - p.meglumine_ratio_pct) * 0.1

    if p.blending_time_min < 15:
        return DCStage1Result(
            content_uniformity_rsd=rsd, blend_potency_pct=potency,
            severity=Severity.WARNING,
            failure_mode=FailureMode.UNDER_BLENDING,
            title="Formulation Warning: Under-Blending",
            description=(
                "Dry blending time below the 15 min corridor threshold. Poor API/"
                "meglumine distribution raises sub-potency risk from solid-state "
                "crystal transitions (catalog Assay alert)."
            ),
        )
    if p.meglumine_ratio_pct < 85:
        return DCStage1Result(
            content_uniformity_rsd=rsd, blend_potency_pct=potency,
            severity=Severity.WARNING,
            failure_mode=FailureMode.MEGLUMINE_DEFICIT,
            title="Formulation Warning: Meglumine Deficit",
            description=(
                "Alkalizer load below 85% of ideal. Insufficient meglumine to hold "
                "Telmisartan in the dissolved state at pH 7.5; downstream dissolution "
                "failure expected at compression."
            ),
        )
    return DCStage1Result(
        content_uniformity_rsd=rsd, blend_potency_pct=potency,
        severity=Severity.OPTIMAL,
        failure_mode=FailureMode.NONE,
        title="Batch Status: Blend Optimal",
        description=(
            "Blending time and alkalizer load within the validated corridor. "
            "Uniform API/meglumine distribution; amorphous state stabilized."
        ),
    )


# ---------------------------------------------------------------------------
# Stage 2 — tablet compression  (chains on Stage 1 CPPs)
# ---------------------------------------------------------------------------
def simulate_dc_stage2(p: DCStage2Params, *, blending_time_min: float,
                       meglumine_ratio_pct: float) -> DCStage2Result:
    """Map compression CPPs (chained with Stage-1 formulation state) to CQAs
    and a single failure mode.

    Illustrative rules (unit-tested):
      * tablet_hardness_kn: 8.0 kN at 32 RPM, +0.15 kN per RPM above 32
        (faster press -> less dwell -> but higher consolidation per the
        illustrative envelope), clamped to [3, 14].
      * dissolution_pct: baseline 90%; three penalties stack:
          - meglumine deficit:  -(100 - meglumine)*0.7  when meglumine < 100
            (meglumine crystallization -> slow release; catalog Dissolution alert)
          - over-compression:   -(rpm - 32)*0.25        when rpm > 32
            (hard/dense tablet -> slow disintegration)
          - under-blending:     -(20 - blend)*0.4       when blend < 20
            (poor meglumine distribution -> variable release)
        At the catalog ideal (20 min, 32 RPM, 100% meglumine) -> 90% (optimal).
      * Failure precedence: dissolution_failure (DANGER) if dissolution < 75%
        — the catalog's primary NSQ alert, checked first. Then
        sticking_hygroscopic (WARNING) if meglumine > 120% — excess alkalizer
        liquefies on compression (catalog Description alert). Else OPTIMAL.
    """
    hardness = max(3.0, min(14.0, 8.0 + (p.rotary_press_rpm - 32.0) * 0.15))

    dissolution = 90.0
    if meglumine_ratio_pct < 100:
        dissolution -= (100.0 - meglumine_ratio_pct) * 0.7
    if p.rotary_press_rpm > 32:
        dissolution -= (p.rotary_press_rpm - 32.0) * 0.25
    if blending_time_min < 20:
        dissolution -= (20.0 - blending_time_min) * 0.4

    if dissolution < 75.0:
        return DCStage2Result(
            tablet_hardness_kn=hardness, dissolution_pct=dissolution,
            severity=Severity.DANGER,
            failure_mode=FailureMode.DISSOLUTION_FAILURE,
            title="Release Failure: Dissolution Below Spec",
            description=(
                f"Projected dissolution {dissolution:.1f}% at 45 min in pH 7.5 "
                "phosphate buffer, below the NLT 75% acceptance threshold. "
                "Meglumine crystallization and/or over-compaction slowed release "
                "(catalog Dissolution alert)."
            ),
        )
    if meglumine_ratio_pct > 120:
        return DCStage2Result(
            tablet_hardness_kn=hardness, dissolution_pct=dissolution,
            severity=Severity.WARNING,
            failure_mode=FailureMode.STICKING_HYGROSCOPIC,
            title="Mechanical Warning: Hygroscopic Sticking",
            description=(
                "Excess meglumine (>120% of ideal) is hygroscopic; on compression "
                "it liquefies at the punch face causing sticking and picking "
                "(catalog Description alert)."
            ),
        )
    return DCStage2Result(
        tablet_hardness_kn=hardness, dissolution_pct=dissolution,
        severity=Severity.OPTIMAL,
        failure_mode=FailureMode.NONE,
        title="Batch Status: Compression Optimal",
        description=(
            "Compaction force and alkalizer load balanced. Disintegration and "
            "dissolution within the NLT 75% / 45 min corridor at pH 7.5."
        ),
    )


# ---------------------------------------------------------------------------
# Route registry metadata + unified simulate() — same shape as telmisartan.py.
# ---------------------------------------------------------------------------
ROUTE_ID = "direct_compression"
ROUTE_LABEL = "Direct Compression (Meglumine alkalizer)"
ROUTE_DESCRIPTION = (
    "The catalog's optimal_process route for telmisartan: dry blending with a "
    "meglumine alkalizer, then direct compression on a rotary press. CPPs and "
    "alerts mirror the curated GMP corridor in gmp_knowledge.py."
)

STAGES = [
    {
        "id": "stage1",
        "label": "Dry Blending",
        "cpps": [
            {"name": "blending_time_min", "label": "Dry Blending Time", "unit": "min",
             "min": 5, "max": 40, "step": 1, "default": 20.0,
             "optimum_low": 15, "optimum_high": 25},
            {"name": "meglumine_ratio_pct", "label": "Meglumine Ratio", "unit": "%",
             "min": 70, "max": 130, "step": 1, "default": 100.0, "target": 100},
        ],
        "cqas": [
            {"name": "content_uniformity_rsd", "label": "Content Uniformity RSD", "unit": "%"},
            {"name": "blend_potency_pct", "label": "Blend Potency", "unit": "%"},
        ],
    },
    {
        "id": "stage2",
        "label": "Tablet Compression",
        "cpps": [
            {"name": "rotary_press_rpm", "label": "Rotary Press Speed", "unit": "RPM",
             "min": 10, "max": 60, "step": 1, "default": 32.0,
             "optimum_low": 20, "optimum_high": 45},
        ],
        "cqas": [
            {"name": "tablet_hardness_kn", "label": "Tablet Hardness", "unit": "kN"},
            {"name": "dissolution_pct", "label": "Dissolution (45 min, pH 7.5)", "unit": "%"},
        ],
    },
]


def simulate(params: dict) -> dict:
    """Run both DC stages from a flat CPP dict and return a route-level result.

    Stage 2 chains on Stage 1's formulation CPPs (blending time + meglumine)
    because dissolution depends on both blending distribution and compaction.
    """
    blend_time = float(params["blending_time_min"])
    meglumine = float(params["meglumine_ratio_pct"])
    press_rpm = float(params["rotary_press_rpm"])

    s1 = simulate_dc_stage1(DCStage1Params(
        blending_time_min=blend_time, meglumine_ratio_pct=meglumine,
    ))
    s2 = simulate_dc_stage2(DCStage2Params(rotary_press_rpm=press_rpm),
                            blending_time_min=blend_time, meglumine_ratio_pct=meglumine)

    overall = _worst(s1.severity, s2.severity)
    if overall == Severity.OPTIMAL:
        overall_fm = FailureMode.NONE
    elif s2.severity == overall:
        overall_fm = s2.failure_mode
    else:
        overall_fm = s1.failure_mode

    return {
        "route_id": ROUTE_ID,
        "route_label": ROUTE_LABEL,
        "stages": [
            {
                "stage_id": "stage1",
                "label": "Dry Blending",
                "cqas": {
                    "content_uniformity_rsd": round(s1.content_uniformity_rsd, 2),
                    "blend_potency_pct": round(s1.blend_potency_pct, 2),
                },
                "severity": s1.severity.value,
                "failure_mode": s1.failure_mode.value,
                "title": s1.title,
                "description": s1.description,
            },
            {
                "stage_id": "stage2",
                "label": "Tablet Compression",
                "cqas": {
                    "tablet_hardness_kn": round(s2.tablet_hardness_kn, 2),
                    "dissolution_pct": round(s2.dissolution_pct, 2),
                },
                "severity": s2.severity.value,
                "failure_mode": s2.failure_mode.value,
                "title": s2.title,
                "description": s2.description,
            },
        ],
        "overall_severity": overall.value,
        "overall_failure_mode": overall_fm.value,
    }