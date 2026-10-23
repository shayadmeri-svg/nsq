"""Three dedicated demo lines, one per product, following how each tablet is made in practice.

    Line 2 · Paracetamol Tablets IP 500 mg (uncoated)
        High-dose, poorly compressible drug: wet granulation with a starch / povidone binder, fluid-bed drying to a low
        LOD, sizing, lubrication, compression of a ~600 mg tablet, strip packing.
    Line 3 · Azithromycin Tablets IP 500 mg (film-coated)
        The dihydrate carries ~4.6 % water of crystallisation: granules are dried cool (inlet ≈ 50 °C) and stopped at a
        LOD near that water content, not dried to 1–2 % — over-drying converts the hydrate. Capsule-shaped ~800 mg
        core, aqueous HPMC film coat (~3 % weight gain), PVC/Al blister.
    Line 4 · Telmisartan Tablets IP 80 mg (uncoated)
        Practically insoluble at gastric pH: as in the originator's formula (sodium hydroxide, meglumine, povidone,
        sorbitol, magnesium stearate), the drug is dissolved alkaline and sprayed onto the filler in a fluid-bed
        processor, blended with sorbitol and lubricant, compressed (~480 mg) and packed in Alu-Alu blisters. The
        product is hygroscopic: compression and packing run in a room held at low humidity.

Process settings (`sim`: what the simulator sends; `params`: the product's ideal and acceptable range on each step)
are typical published values for this kind of product, for the demo — not a manufacturer's validated ranges. The
weight-uniformity ranges are the pharmacopoeial ±5 % (tablets over 250 mg). Machine makers are ones that build that
kind of machine; the models are left blank (nothing here was read from a real machine).
"""

from __future__ import annotations

from typing import Any

TYPICAL = "Typical published process value for this kind of product (demo) — replace with your validated range"
UOW = "Uniformity of weight: ±5 % for tablets over 250 mg (IP / Ph. Eur. 2.9.5)"


def _sig(setpoint: float, noise: float = 0.0, pattern: str = "steady", amplitude: float = 0.0, per: str = "reading") -> dict[str, Any]:
    """A simulator signal. `ramp` rises to the setpoint over the step by `amplitude` (negative: falls to it)."""
    return {"setpoint": setpoint, "noise": noise, "pattern": pattern, "amplitude": amplitude, "per": per}


def _lim(ideal: float, lo: float, hi: float, check: str = "continuous", source: str = TYPICAL) -> dict[str, Any]:
    return {"ideal": ideal, "lo": lo, "hi": hi, "check": check, "source": source}


LINES: list[dict[str, Any]] = [
    {"line": "Line 2 · Paracetamol",
     "product": {"name": "Paracetamol Tablets IP 500 mg · Line 2", "code": "PCM500-L2", "molecule_key": "paracetamol", "dosage_form": "tablet", "color": "#0ea5e9"},
     "machines": [
         {"name": "SFT-201", "type": "sifter", "make": "Gansons", "minutes": 20,
          "sim": {"throughput_kg_h": _sig(800, 15), "motor_a": _sig(4.2, 0.1), "run_min": _sig(20, 0, "ramp", 20)}},
         {"name": "RMG-201", "type": "rmg", "make": "Bectochem", "minutes": 25,
          "sim": {"dry_mix_kg": _sig(200, 0, per="batch"), "binder_kg": _sig(44, 0.8, per="batch"), "wet_mix_min": _sig(3, 0.15, per="batch"),
                  "impeller_kw": _sig(18, 0.4, "ramp", 9)},
          "params": {"binder_kg": _lim(44, 40, 48, "end"), "wet_mix_min": _lim(3, 2.5, 3.5, "end")}},
         {"name": "FBD-201", "type": "fbd", "make": "Glatt", "minutes": 45,
          "sim": {"inlet_c": _sig(65, 0.6), "outlet_c": _sig(42, 0.4, "ramp", 14), "product_c": _sig(45, 0.4, "ramp", 18),
                  "inlet_rh_pct": _sig(8, 0.5), "air_m3_h": _sig(3000, 40), "lod_pct": _sig(1.5, 0.05, "ramp", -16.5), "elapsed_min": _sig(45, 0, "ramp", 45)},
          "params": {"inlet_c": _lim(65, 60, 70), "lod_pct": _lim(1.5, 1.0, 2.5, "end"), "product_c": _lim(45, 38, 50, "end")}},
         {"name": "MIL-201", "type": "mill", "make": "Quadro (IDEX)", "minutes": 20,
          "sim": {"rotor_rpm": _sig(1500, 10), "motor_kw": _sig(5, 0.2), "feed_kg_h": _sig(600, 15), "screen_mm": _sig(1.5)}},
         {"name": "BLD-201", "type": "blender", "make": "Gansons", "minutes": 25,
          "sim": {"blend_min": _sig(5, 0.2, per="batch"), "blender_rpm": _sig(12, 0.2)},
          "params": {"blend_min": _lim(5, 4, 6, "end")}},
         {"name": "CMP-201", "type": "press", "make": "Cadmach", "minutes": 60,
          "sim": {"force_kn": _sig(15, 0.5), "precompression_kn": _sig(3, 0.15), "tablet_weight_mg": _sig(600, 3), "press_rpm": _sig(30, 0.3),
                  "punch_diameter_mm": _sig(12.7)},
          "params": {"force_kn": _lim(15, 12, 18), "tablet_weight_mg": _lim(600, 570, 630, source=UOW)}},
         {"name": "STP-201", "type": "strip_packing", "make": "ACG Pampac", "minutes": 50,
          "sim": {"sealing_c": _sig(175, 1.2), "speed_cpm": _sig(120, 2)},
          "params": {"sealing_c": _lim(175, 165, 185)}},
     ]},
    {"line": "Line 3 · Azithromycin",
     "product": {"name": "Azithromycin Tablets IP 500 mg · Line 3", "code": "AZI500-L3", "molecule_key": "azithromycin", "dosage_form": "film-coated tablet", "color": "#8b5cf6"},
     "machines": [
         {"name": "SFT-301", "type": "sifter", "make": "Russell Finex", "minutes": 20,
          "sim": {"throughput_kg_h": _sig(600, 12), "motor_a": _sig(3.8, 0.1), "run_min": _sig(20, 0, "ramp", 20)}},
         {"name": "RMG-301", "type": "rmg", "make": "Diosna", "minutes": 25,
          "sim": {"dry_mix_kg": _sig(150, 0, per="batch"), "binder_kg": _sig(30, 0.6, per="batch"), "wet_mix_min": _sig(4, 0.2, per="batch"),
                  "impeller_kw": _sig(14, 0.3, "ramp", 7)},
          "params": {"binder_kg": _lim(30, 27, 33, "end"), "wet_mix_min": _lim(4, 3, 5, "end")}},
         {"name": "FBD-301", "type": "fbd", "make": "GEA (Aeromatic-Fielder)", "minutes": 60,
          "sim": {"inlet_c": _sig(50, 0.5), "outlet_c": _sig(36, 0.4, "ramp", 10), "product_c": _sig(38, 0.4, "ramp", 12),
                  "inlet_rh_pct": _sig(10, 0.5), "air_m3_h": _sig(2500, 35), "lod_pct": _sig(4.5, 0.06, "ramp", -14), "elapsed_min": _sig(60, 0, "ramp", 60)},
          "params": {"inlet_c": _lim(50, 45, 55), "lod_pct": _lim(4.5, 3.5, 5.5, "end",
                                                                   "Dihydrate: stop near its ~4.6 % water of crystallisation (typical; demo)"),
                     "product_c": _lim(38, 32, 42, "end")}},
         {"name": "MIL-301", "type": "mill", "make": "Frewitt", "minutes": 20,
          "sim": {"rotor_rpm": _sig(1200, 10), "motor_kw": _sig(4, 0.2), "feed_kg_h": _sig(450, 12), "screen_mm": _sig(1.2)}},
         {"name": "BLD-301", "type": "blender", "make": "L.B. Bohle", "minutes": 25,
          "sim": {"blend_min": _sig(6, 0.2, per="batch"), "blender_rpm": _sig(10, 0.2)},
          "params": {"blend_min": _lim(6, 5, 7, "end")}},
         {"name": "CMP-301", "type": "press", "make": "Fette Compacting", "minutes": 60,
          "sim": {"force_kn": _sig(20, 0.6), "precompression_kn": _sig(4, 0.2), "tablet_weight_mg": _sig(800, 4), "press_rpm": _sig(25, 0.3),
                  "punch_diameter_mm": _sig(19)},
          "params": {"force_kn": _lim(20, 16, 24), "tablet_weight_mg": _lim(800, 760, 840, source=UOW)}},
         {"name": "COT-301", "type": "coater", "make": "ACG", "minutes": 90,
          "sim": {"weight_gain_pct": _sig(3.0, 0.02, "ramp", 3.0), "coat_inlet_c": _sig(58, 0.5), "exhaust_c": _sig(42, 0.4),
                  "spray_g_min": _sig(120, 3), "pan_rpm": _sig(7, 0.1), "atomizing_bar": _sig(2.0, 0.03)},
          "params": {"weight_gain_pct": _lim(3.0, 2.5, 3.5, "end"), "coat_inlet_c": _lim(58, 55, 62), "exhaust_c": _lim(42, 40, 45),
                     "spray_g_min": _lim(120, 100, 140), "pan_rpm": _lim(7, 5, 9), "atomizing_bar": _lim(2.0, 1.8, 2.5)}},
         {"name": "BLS-301", "type": "blister", "make": "Uhlmann", "minutes": 50,
          "sim": {"sealing_c": _sig(190, 1.2), "forming_c": _sig(130, 1), "speed_cpm": _sig(200, 3), "rejects": _sig(4, 1)},
          "params": {"sealing_c": _lim(190, 180, 200), "forming_c": _lim(130, 120, 140)}},
     ]},
    {"line": "Line 4 · Telmisartan",
     "product": {"name": "Telmisartan Tablets IP 80 mg · Line 4", "code": "TEL80-L4", "molecule_key": "telmisartan", "dosage_form": "tablet", "color": "#10b981"},
     "machines": [
         {"name": "FBP-401", "type": "fbp", "make": "Glatt", "minutes": 75,
          "sim": {"product_c": _sig(38, 0.4), "spray_g_min": _sig(250, 5), "inlet_c": _sig(65, 0.6), "exhaust_c": _sig(35, 0.4),
                  "atomizing_bar": _sig(2.5, 0.04), "air_m3_h": _sig(2000, 30), "filter_dp_pa": _sig(1200, 40, "ramp", 600)},
          "params": {"product_c": _lim(38, 35, 42), "spray_g_min": _lim(250, 220, 280), "inlet_c": _lim(65, 60, 70)}},
         {"name": "BLD-401", "type": "blender", "make": "L.B. Bohle", "minutes": 25,
          "sim": {"blend_min": _sig(10, 0.3, per="batch"), "blender_rpm": _sig(10, 0.2)},
          "params": {"blend_min": _lim(10, 8, 12, "end")}},
         {"name": "CMP-401", "type": "press", "make": "Korsch", "minutes": 60,
          "sim": {"force_kn": _sig(10, 0.4), "precompression_kn": _sig(2, 0.1), "tablet_weight_mg": _sig(480, 2.5), "press_rpm": _sig(35, 0.3),
                  "punch_diameter_mm": _sig(11)},
          "params": {"force_kn": _lim(10, 8, 12), "tablet_weight_mg": _lim(480, 456, 504, source=UOW)}},
         {"name": "BLS-401", "type": "blister", "make": "Uhlmann", "minutes": 50,
          "sim": {"sealing_c": _sig(200, 1.2), "forming_c": _sig(25, 0.3), "speed_cpm": _sig(150, 3), "rejects": _sig(3, 1)},
          "params": {"sealing_c": _lim(200, 190, 210)}},
         {"name": "HVAC-401", "type": "hvac_room", "make": "Vaisala", "minutes": 0,
          "sim": {"room_c": _sig(22, 0.15), "room_rh_pct": _sig(35, 0.6, "sine", 2.5), "dp_pa": _sig(15, 0.5)}},
     ]},
]
MACHINES = {m["name"]: {**m, "line": ln["line"], "position": i, "product": ln["product"]["code"]}
            for ln in LINES for i, m in enumerate(ln["machines"])}
