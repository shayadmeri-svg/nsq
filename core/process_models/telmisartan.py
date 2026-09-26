"""Telmisartan manufacturing process simulator — pure domain model.

Two-stage wet-granulation route (spray-solution preparation -> fluid-bed
granulation), faithful to the interactive QbD prototype. Critical Process
Parameters (CPPs) map to Critical Quality Attributes (CQAs) and failure
modes via transparent, unit-testable rules. This is the seam: a future
mechanistic / pharmacokinetic model can replace the illustrative rules
below without touching the API or the UI, because everything downstream
consumes only the typed result dataclasses.

Route vs. the curated catalog
-----------------------------
The GMP corridor in analytics/shared/gmp_knowledge.py for telmisartan
(id="telmisartan") specifies **Direct Compression** with a meglumine
alkalizer (ideal_parameters: Dry Blending Time 15-25 min, Rotary Press
Speed 20-45 RPM). This simulator models a DIFFERENT but real industrial
route: amorphous sodium-salt formation via NaOH in a spray solution,
followed by fluid-bed granulation. The two routes share the downstream
dissolution target carried by the catalog — NLT 75% in 45 min in pH 7.5
phosphate buffer per IP 2026 / Ph. Eur. — but differ in unit operations
and CPPs. The divergence is intentional and documented so a future
direct-compression model can live alongside this one under
process_models/ and be selected by route.

Everything here is deterministic and side-effect-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Severity(str, Enum):
    """Evidentiary severity of a process state, ordered OPTIMAL < WARNING < DANGER.

    str mixin so values serialise to JSON as-is (no .value dance at the API
    boundary) and stay comparable across the model, API, and UI."""

    OPTIMAL = "optimal"
    WARNING = "warning"
    DANGER = "danger"


class FailureMode(str, Enum):
    """The named defect mode the current CPP combination drives, or NONE.

    One failure mode per result — the model does not stack defects. The
    precedence (which mode wins when several conditions are true) is part
    of the contract and is unit-tested. Members cover BOTH telmisartan
    routes (NaOH fluid-bed + direct-compression) so the API/UI can render
    a single failure-mode vocabulary across the route selector."""

    NONE = "none"
    # NaOH fluid-bed route — Stage 1
    CRYSTALLINE_PRECIPITATION = "crystalline_precipitation"
    POLYMER_SHEAR = "polymer_shear"
    # NaOH fluid-bed route — Stage 2
    BED_OVER_WETTING = "bed_over_wetting"
    SPRAY_DRYING_FINES = "spray_drying_fines"
    # Direct-compression route — Stage 1 (blending)
    UNDER_BLENDING = "under_blending"
    MEGLUMINE_DEFICIT = "meglumine_deficit"
    # Direct-compression route — Stage 2 (compression)
    DISSOLUTION_FAILURE = "dissolution_failure"
    STICKING_HYGROSCOPIC = "sticking_hygroscopic"


# ---------------------------------------------------------------------------
# CPP inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stage1Params:
    """Spray-solution preparation CPPs.

    Ranges and optima mirror the validated bounds of the QbD prototype; they
    are the contract the API and UI both read (STAGE1_RANGES) so the slider
    min/max/step never drift from the model."""

    mixing_temp_c: float = 40.0       # 15..70, optimum 35-45 C
    naoh_ratio_pct: float = 100.0    # 70..130, stoichiometric target 100%
    mixing_time_min: float = 45.0    # 5..90, required >= 30 min


@dataclass(frozen=True)
class Stage2Params:
    """Fluid-bed granulation CPPs."""

    inlet_air_temp_c: float = 60.0            # 35..85, optimum 55-65 C
    spray_rate_g_min: float = 50.0            # 15..100, optimum 40-60 g/min
    atomization_pressure_bar: float = 2.0     # 0.5..4.0, optimum 1.5-2.5 bar


# ---------------------------------------------------------------------------
# CQA outputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stage1Result:
    ph: float                       # solution pH (amorphous-salt formation proxy)
    viscosity_cp: float            # PVP K-30 matrix viscosity, centipoise
    severity: Severity
    failure_mode: FailureMode
    title: str
    description: str


@dataclass(frozen=True)
class Stage2Result:
    bed_moisture_pct: float        # residual granule moisture
    mean_granule_size_um: float    # volume-weighted mean granule diameter
    severity: Severity
    failure_mode: FailureMode
    title: str
    description: str


# ---------------------------------------------------------------------------
# Range contracts — single source of truth for min/max/optimum, shared with
# the API and any UI so slider bounds never drift from the model.
# ---------------------------------------------------------------------------
STAGE1_RANGES: dict[str, dict[str, float]] = {
    "mixing_temp_c":    {"min": 15, "max": 70, "optimum_low": 35, "optimum_high": 45, "step": 1},
    "naoh_ratio_pct":   {"min": 70, "max": 130, "target": 100, "step": 1},
    "mixing_time_min":  {"min": 5, "max": 90, "required_min": 30, "step": 1},
}
STAGE2_RANGES: dict[str, dict[str, float]] = {
    "inlet_air_temp_c":          {"min": 35, "max": 85, "optimum_low": 55, "optimum_high": 65, "step": 1},
    "spray_rate_g_min":          {"min": 15, "max": 100, "optimum_low": 40, "optimum_high": 60, "step": 1},
    "atomization_pressure_bar":  {"min": 0.5, "max": 4.0, "optimum_low": 1.5, "optimum_high": 2.5, "step": 0.1},
}


# ---------------------------------------------------------------------------
# Stage 1 — spray-solution preparation
# ---------------------------------------------------------------------------
def simulate_stage1(p: Stage1Params) -> Stage1Result:
    """Map Stage-1 CPPs to CQAs + a single failure mode.

    Rules (illustrative, unit-tested):
      * pH is a strong function of the NaOH stoichiometric ratio:
        pH = 7.0 + 4.2 * (NaOH/100), capped at 14.0. At 100% -> 11.2.
      * Viscosity: PVP K-30 base 320 cP. Thermal shear above 50 C thins it;
        cold sludge below 30 C thickens it. Linear within each regime.
      * Failure precedence: crystalline_precipitation (DANGER) is checked
        first — under-solubilization dominates everything else. Then
        polymer_shear (WARNING) above 50 C. Else OPTIMAL.
    """
    ph = min(14.0, 7.0 + 4.2 * (p.naoh_ratio_pct / 100.0))

    if p.mixing_temp_c > 50:
        viscosity = max(80.0, 320.0 - (p.mixing_temp_c - 50) * 11)
    elif p.mixing_temp_c < 30:
        viscosity = 320.0 + (30 - p.mixing_temp_c) * 15
    else:
        viscosity = 320.0

    if p.naoh_ratio_pct < 90 or p.mixing_time_min < 30 or p.mixing_temp_c < 30:
        return Stage1Result(
            ph=ph, viscosity_cp=viscosity,
            severity=Severity.DANGER,
            failure_mode=FailureMode.CRYSTALLINE_PRECIPITATION,
            title="Crystalline Defect: Low Solubilization",
            description=(
                "Low pH or insufficient thermal kinetic energy failed to convert "
                "Telmisartan into the amorphous sodium salt. Crystalline precipitation "
                "expected in downstream line filters."
            ),
        )
    if p.mixing_temp_c > 50:
        return Stage1Result(
            ph=ph, viscosity_cp=viscosity,
            severity=Severity.WARNING,
            failure_mode=FailureMode.POLYMER_SHEAR,
            title="Excipient Warning: Polymer Degradation",
            description=(
                "Elevated processing temperature (>50 C) thermally shears the Povidone "
                "(PVP K-30) chains. Binding functionality compromised."
            ),
        )
    return Stage1Result(
        ph=ph, viscosity_cp=viscosity,
        severity=Severity.OPTIMAL,
        failure_mode=FailureMode.NONE,
        title="Batch Status: Optimal Solution",
        description=(
            "Parameters conform to validated thresholds. Complete transition to "
            "dissolved amorphous salt achieved."
        ),
    )


# ---------------------------------------------------------------------------
# Stage 2 — fluid-bed granulation
# ---------------------------------------------------------------------------
def simulate_stage2(p: Stage2Params) -> Stage2Result:
    """Map Stage-2 CPPs to CQAs + a single failure mode.

    Rules (illustrative, unit-tested):
      * Evaporation deficit = (spray/50) - (inlet_temp/60). Positive =>
        liquid delivered faster than drying capacity; negative => over-drying.
      * Bed moisture = 2.4 + deficit*3.5, floored at 0.5%.
      * Mean granule size = 180 + deficit*150 - (pressure-2.0)*40, floored at 40 um.
        Higher atomization pressure -> finer droplets -> smaller granules.
      * Failure precedence: bed_over_wetting (DANGER, moisture > 5.5) is
        checked first — a collapsed bed is the worst outcome. Then
        spray_drying_fines (WARNING) if moisture < 1.0 OR pressure > 3.2 OR
        inlet > 75. Else OPTIMAL.
    """
    evap_deficit = (p.spray_rate_g_min / 50.0) - (p.inlet_air_temp_c / 60.0)
    moisture = max(0.5, 2.4 + evap_deficit * 3.5)
    granule = max(40.0, 180.0 + evap_deficit * 150.0 - (p.atomization_pressure_bar - 2.0) * 40.0)

    if moisture > 5.5:
        return Stage2Result(
            bed_moisture_pct=moisture, mean_granule_size_um=granule,
            severity=Severity.DANGER,
            failure_mode=FailureMode.BED_OVER_WETTING,
            title="Mechanical Defect: Bed Over-Wetting",
            description=(
                "High spray rate with insufficient drying has caused liquid pooling. "
                "Fluidized bed collapsed; fluidization stalled."
            ),
        )
    if moisture < 1.0 or p.atomization_pressure_bar > 3.2 or p.inlet_air_temp_c > 75:
        return Stage2Result(
            bed_moisture_pct=moisture, mean_granule_size_um=granule,
            severity=Severity.WARNING,
            failure_mode=FailureMode.SPRAY_DRYING_FINES,
            title="Yield Loss: Spray Drying Fines",
            description=(
                "Excessive atomization pressure or high inlet temperature dries droplets "
                "before bed contact. Static fine generation; yield loss to dust filtration."
            ),
        )
    return Stage2Result(
        bed_moisture_pct=moisture, mean_granule_size_um=granule,
        severity=Severity.OPTIMAL,
        failure_mode=FailureMode.NONE,
        title="Batch Status: Fluidizing Optimal",
        description=(
            "Thermodynamic mass balance achieved. Stable capillary liquid bonding; "
            "clean granule matrix distribution."
        ),
    )


# ---------------------------------------------------------------------------
# Route registry metadata + unified simulate() — the seam the API/UI consume.
# Both telmisartan routes expose the same shape (ROUTE_ID, ROUTE_LABEL, STAGES,
# simulate(params)->dict) so the route selector can render any route from its
# metadata alone, with no route-specific code in the API or the UI.
# ---------------------------------------------------------------------------
ROUTE_ID = "naoh_fluidbed"
ROUTE_LABEL = "NaOH amorphous salt + Fluid-Bed Granulation"
ROUTE_DESCRIPTION = (
    "Wet-granulation route: amorphous sodium-salt formation in a NaOH spray "
    "solution, then fluid-bed granulation. The CPPs and failure modes mirror "
    "the validated QbD prototype."
)

STAGES = [
    {
        "id": "stage1",
        "label": "Spray Solution Prep",
        "cpps": [
            {"name": "mixing_temp_c", "label": "Mixing Temperature", "unit": "°C",
             "min": 15, "max": 70, "step": 1, "default": 40.0,
             "optimum_low": 35, "optimum_high": 45},
            {"name": "naoh_ratio_pct", "label": "NaOH Ratio", "unit": "%",
             "min": 70, "max": 130, "step": 1, "default": 100.0, "target": 100},
            {"name": "mixing_time_min", "label": "Mixing Time", "unit": "min",
             "min": 5, "max": 90, "step": 1, "default": 45.0, "required_min": 30},
        ],
        "cqas": [
            {"name": "ph", "label": "Solution pH", "unit": ""},
            {"name": "viscosity_cp", "label": "Viscosity", "unit": "cP"},
        ],
    },
    {
        "id": "stage2",
        "label": "Fluid Bed Granulation",
        "cpps": [
            {"name": "inlet_air_temp_c", "label": "Inlet Air Temp", "unit": "°C",
             "min": 35, "max": 85, "step": 1, "default": 60.0,
             "optimum_low": 55, "optimum_high": 65},
            {"name": "spray_rate_g_min", "label": "Spray Rate", "unit": "g/min",
             "min": 15, "max": 100, "step": 1, "default": 50.0,
             "optimum_low": 40, "optimum_high": 60},
            {"name": "atomization_pressure_bar", "label": "Atomization Pressure", "unit": "bar",
             "min": 0.5, "max": 4.0, "step": 0.1, "default": 2.0,
             "optimum_low": 1.5, "optimum_high": 2.5},
        ],
        "cqas": [
            {"name": "bed_moisture_pct", "label": "Bed Moisture", "unit": "%"},
            {"name": "mean_granule_size_um", "label": "Mean Granule Size", "unit": "µm"},
        ],
    },
]

_SEVERITY_RANK = {Severity.OPTIMAL: 0, Severity.WARNING: 1, Severity.DANGER: 2}


def _worst(*severities: Severity) -> Severity:
    return max(severities, key=lambda s: _SEVERITY_RANK[s])


def simulate(params: dict) -> dict:
    """Run both stages from a flat CPP dict and return a route-level result.

    The shape is shared with the direct-compression route so the API serialises
    every route identically:
        {route_id, route_label, stages: [{stage_id, label, cqas, severity,
         failure_mode, title, description}], overall_severity, overall_failure_mode}
    """
    s1 = simulate_stage1(Stage1Params(
        mixing_temp_c=float(params["mixing_temp_c"]),
        naoh_ratio_pct=float(params["naoh_ratio_pct"]),
        mixing_time_min=float(params["mixing_time_min"]),
    ))
    s2 = simulate_stage2(Stage2Params(
        inlet_air_temp_c=float(params["inlet_air_temp_c"]),
        spray_rate_g_min=float(params["spray_rate_g_min"]),
        atomization_pressure_bar=float(params["atomization_pressure_bar"]),
    ))
    overall = _worst(s1.severity, s2.severity)
    overall_fm = s1.failure_mode if s1.severity == overall else s2.failure_mode
    if overall == Severity.OPTIMAL:
        overall_fm = FailureMode.NONE
    return {
        "route_id": ROUTE_ID,
        "route_label": ROUTE_LABEL,
        "stages": [
            {
                "stage_id": "stage1",
                "label": "Spray Solution Prep",
                "cqas": {"ph": round(s1.ph, 2), "viscosity_cp": round(s1.viscosity_cp, 1)},
                "severity": s1.severity.value,
                "failure_mode": s1.failure_mode.value,
                "title": s1.title,
                "description": s1.description,
            },
            {
                "stage_id": "stage2",
                "label": "Fluid Bed Granulation",
                "cqas": {
                    "bed_moisture_pct": round(s2.bed_moisture_pct, 2),
                    "mean_granule_size_um": round(s2.mean_granule_size_um, 1),
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