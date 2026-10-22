"""What Eurveda Connect can talk to and what it knows about plant equipment.

PROTOCOLS — how a source is reached. `status`: available (the edge agent speaks it today), beta (works, little field
use), planned (listed so a plant can say what it has; built on demand, e.g. through Apache PLC4X or a Kepware bridge).

EQUIPMENT_TYPES — templates: one per kind of machine, with the signals Eurveda understands (the same field ids as
Plant data, core/chem/batch_data.py), their units and a typical range, and name hints used to suggest a tag mapping
from a machine's own tag names (as in Seeq's Tree Builder: rules on names, the user confirms).

PROFILES — tag maps for a specific machine model, so the second plant with the same model connects without mapping.
Only profiles verified against a real machine belong here; today that is the Eurveda simulator. OEM profiles are
added during onboarding, from the machine itself — never guessed.
"""

from __future__ import annotations

import re
from typing import Any, Optional

PROTOCOLS: list[dict[str, Any]] = [
    {"id": "opcua", "label": "OPC UA", "status": "available", "kind": "machine",
     "what": "Modern PLCs, SCADA and most new machines. Read-only, browsable tags.",
     "fields": [{"id": "endpoint", "label": "Endpoint", "placeholder": "opc.tcp://10.0.0.20:4840", "required": True},
                {"id": "security", "label": "Security", "placeholder": "Basic256Sha256,SignAndEncrypt,cert.der,key.pem"},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "modbus_tcp", "label": "Modbus TCP", "status": "available", "kind": "machine",
     "what": "Older panels, dryers, utilities, meters. Register addresses from the machine's manual.",
     "fields": [{"id": "host", "label": "Host", "placeholder": "192.168.1.30", "required": True},
                {"id": "port", "label": "Port", "placeholder": "502"}, {"id": "unit", "label": "Unit id", "placeholder": "1"},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "mqtt", "label": "MQTT / Sparkplug B", "status": "beta", "kind": "machine",
     "what": "IoT gateways and newer edge boxes publishing to a broker.",
     "fields": [{"id": "broker", "label": "Broker", "placeholder": "mqtt://10.0.0.5:1883", "required": True},
                {"id": "topic", "label": "Topic", "placeholder": "plant/line1/fbd1/#"}]},
    {"id": "s7", "label": "Siemens S7 (native)", "status": "planned", "kind": "machine",
     "what": "S7-300/400/1200/1500 PLCs without OPC UA (via Apache PLC4X / snap7).", "fields": []},
    {"id": "ethernet_ip", "label": "Rockwell EtherNet/IP", "status": "planned", "kind": "machine",
     "what": "ControlLogix / CompactLogix tag reads (via pycomm3 / PLC4X).", "fields": []},
    {"id": "historian", "label": "Historian (PI, SQL)", "status": "planned", "kind": "system",
     "what": "AVEVA PI Web API, SQL-based historians: read what SCADA already stores.", "fields": []},
    {"id": "ebmr", "label": "eBMR / LIMS export", "status": "planned", "kind": "system",
     "what": "Batch records and QC results from AmpleLogic-, Caliber-type systems (API or scheduled export).", "fields": []},
    {"id": "file", "label": "File drop (CSV / Excel)", "status": "available", "kind": "file",
     "what": "Exports from any machine or system, uploaded or dropped in a watched folder.", "fields": []},
    {"id": "manual", "label": "Manual entry", "status": "available", "kind": "file",
     "what": "Paper-based steps: the operator types readings on a tablet.", "fields": []},
]
PROTOCOL_BY_ID = {p["id"]: p for p in PROTOCOLS}


def _s(id: str, label: str, unit: str, lo: float, hi: float, hints: str, key: bool = False) -> dict[str, Any]:
    return {"id": id, "label": label, "unit": unit, "typical": [lo, hi], "hints": hints, "key": key}


EQUIPMENT_TYPES: list[dict[str, Any]] = [
    {"id": "rmg", "label": "Rapid mixer granulator", "stage": "Granulation", "dosage_forms": ["tablet", "capsule"], "signals": [
        _s("binder_kg", "Binder solution added", "kg", 5, 60, r"binder|solution|liquid|water.?add", True),
        _s("dry_mix_kg", "Dry mix", "kg", 20, 300, r"dry.?mix|batch.?size|load"),
        _s("wet_mix_min", "Wet mixing time", "min", 0.5, 15, r"wet.?mix|knead"),
        _s("impeller_kw", "Impeller power", "kW", 0, 30, r"impeller|power|kw|load")]},
    {"id": "fbd", "label": "Fluid-bed dryer", "stage": "Drying", "dosage_forms": ["tablet", "capsule"], "signals": [
        _s("lod_pct", "Loss on drying", "%", 0, 25, r"\blod\b|moist", True),
        _s("inlet_c", "Inlet air temperature", "°C", 25, 95, r"inlet.?t|supply.?t|tt.?1?01", True),
        _s("outlet_c", "Outlet air temperature", "°C", 20, 80, r"outlet|exhaust"),
        _s("product_c", "Product temperature", "°C", 20, 70, r"product|bed"),
        _s("inlet_rh_pct", "Inlet relative humidity", "%RH", 0, 90, r"\brh\b|humid"),
        _s("air_m3_h", "Air flow", "m³/h", 500, 6000, r"air.?flow|cmh|airflow"),
        _s("elapsed_min", "Elapsed drying time", "min", 0, 180, r"elapsed|timer|run.?time")]},
    {"id": "blender", "label": "Blender", "stage": "Blending", "dosage_forms": ["tablet", "capsule"], "signals": [
        _s("blend_min", "Blend time", "min", 0.5, 40, r"blend|mix.?time|lube", True),
        _s("blender_rpm", "Blender speed", "rpm", 2, 40, r"rpm|speed")]},
    {"id": "press", "label": "Tablet press", "stage": "Compression", "dosage_forms": ["tablet"], "signals": [
        _s("force_kn", "Main compression force", "kN", 1, 60, r"main.?force|compression|mcf|\bforce", True),
        _s("tablet_weight_mg", "Tablet weight", "mg", 100, 1500, r"weight|\bwt\b", True),
        _s("precompression_kn", "Pre-compression force", "kN", 0, 10, r"pre.?comp|pcf"),
        _s("press_rpm", "Turret speed", "rpm", 5, 90, r"turret|speed|rpm"),
        _s("punch_diameter_mm", "Punch diameter", "mm", 5, 25, r"punch|dia")]},
    {"id": "coater", "label": "Pan coater", "stage": "Coating", "dosage_forms": ["tablet"], "signals": [
        _s("weight_gain_pct", "Coating weight gain", "%", 0, 6, r"weight.?gain|gain", True),
        _s("coat_inlet_c", "Inlet air temperature", "°C", 30, 80, r"inlet.?t|supply", True),
        _s("exhaust_c", "Exhaust temperature", "°C", 25, 60, r"exhaust|outlet"),
        _s("spray_g_min", "Spray rate", "g/min", 10, 400, r"spray"),
        _s("pan_rpm", "Pan speed", "rpm", 1, 20, r"pan|drum|rpm"),
        _s("atomizing_bar", "Atomizing air pressure", "bar", 0.5, 4, r"atomi|aap")]},
    {"id": "capsule_filler", "label": "Capsule filler", "stage": "Encapsulation", "dosage_forms": ["capsule"], "signals": [
        _s("fill_weight_mg", "Fill weight", "mg", 50, 1000, r"fill.?w|weight", True),
        _s("filler_speed_cph", "Speed", "capsules/h", 1000, 200000, r"speed|output|cph")]},
    {"id": "liquid_vessel", "label": "Liquid manufacturing vessel", "stage": "Compounding", "dosage_forms": ["oral liquid", "injectable"], "signals": [
        _s("vessel_c", "Product temperature", "°C", 5, 90, r"temp|tt", True),
        _s("agitator_rpm", "Agitator speed", "rpm", 10, 1500, r"agit|stirr|rpm"),
        _s("ph", "pH", "pH", 1, 13, r"\bph\b"),
        _s("level_l", "Level", "L", 0, 10000, r"level|volume")]},
    {"id": "filling_line", "label": "Filling line", "stage": "Filling", "dosage_forms": ["oral liquid", "injectable"], "signals": [
        _s("fill_volume_ml", "Fill volume", "mL", 1, 1000, r"fill.?vol|volume", True),
        _s("line_speed_bpm", "Line speed", "units/min", 10, 600, r"speed|bpm|upm")]},
    {"id": "autoclave", "label": "Autoclave / sterilizer", "stage": "Sterilisation", "dosage_forms": ["injectable"], "signals": [
        _s("chamber_c", "Chamber temperature", "°C", 20, 140, r"chamber|temp", True),
        _s("chamber_bar", "Chamber pressure", "bar", 0, 4, r"press"),
        _s("f0_min", "F0", "min", 0, 60, r"\bf0\b|lethal")]},
    {"id": "hvac_room", "label": "Room / HVAC monitoring", "stage": "Environment", "dosage_forms": ["tablet", "capsule", "oral liquid", "injectable"], "signals": [
        _s("room_c", "Room temperature", "°C", 15, 30, r"temp|tt", True),
        _s("room_rh_pct", "Room humidity", "%RH", 20, 70, r"\brh\b|humid", True),
        _s("dp_pa", "Differential pressure", "Pa", 0, 60, r"\bdp\b|diff.?press|pa\b")]},
]
TYPE_BY_ID = {t["id"]: t for t in EQUIPMENT_TYPES}
DOSAGE_FORMS = ["tablet", "film-coated tablet", "capsule", "oral liquid", "injectable"]

# Machine-model tag maps, verified against the machine they describe (protocol, type, {signal: tag}).
PROFILES: list[dict[str, Any]] = [
    {"id": "eurveda-sim-rmg", "label": "Eurveda plant simulator · RMG1", "type": "rmg", "protocol": "opcua", "verified": "simulator",
     "batch_tag": "ns=2;s=RMG1.BatchNo", "product_tag": "ns=2;s=RMG1.Product",
     "tags": {"binder_kg": "ns=2;s=RMG1.BinderKg", "dry_mix_kg": "ns=2;s=RMG1.DryMixKg", "wet_mix_min": "ns=2;s=RMG1.WetMixMin", "impeller_kw": "ns=2;s=RMG1.ImpellerKW"}},
    {"id": "eurveda-sim-fbd", "label": "Eurveda plant simulator · FBD1", "type": "fbd", "protocol": "opcua", "verified": "simulator",
     "batch_tag": "ns=2;s=FBD1.BatchNo", "product_tag": "ns=2;s=FBD1.Product",
     "tags": {"inlet_c": "ns=2;s=FBD1.InletTemp", "outlet_c": "ns=2;s=FBD1.OutletTemp", "product_c": "ns=2;s=FBD1.ProductTemp",
              "inlet_rh_pct": "ns=2;s=FBD1.InletRH", "air_m3_h": "ns=2;s=FBD1.AirFlow", "lod_pct": "ns=2;s=FBD1.LOD", "elapsed_min": "ns=2;s=FBD1.ElapsedMin"}},
    {"id": "eurveda-sim-blender", "label": "Eurveda plant simulator · BLEND1", "type": "blender", "protocol": "opcua", "verified": "simulator",
     "batch_tag": "ns=2;s=BLEND1.BatchNo", "product_tag": "ns=2;s=BLEND1.Product",
     "tags": {"blend_min": "ns=2;s=BLEND1.BlendMin", "blender_rpm": "ns=2;s=BLEND1.SpeedRPM"}},
    {"id": "eurveda-sim-press", "label": "Eurveda plant simulator · PRESS1", "type": "press", "protocol": "opcua", "verified": "simulator",
     "batch_tag": "ns=2;s=PRESS1.BatchNo", "product_tag": "ns=2;s=PRESS1.Product",
     "tags": {"force_kn": "ns=2;s=PRESS1.ForceKN", "precompression_kn": "ns=2;s=PRESS1.PrecompKN", "tablet_weight_mg": "ns=2;s=PRESS1.TabletWeightMg",
              "punch_diameter_mm": "ns=2;s=PRESS1.PunchDiameterMm", "press_rpm": "ns=2;s=PRESS1.TurretRPM"}},
    {"id": "eurveda-sim-coater", "label": "Eurveda plant simulator · COAT1", "type": "coater", "protocol": "opcua", "verified": "simulator",
     "batch_tag": "ns=2;s=COAT1.BatchNo", "product_tag": "ns=2;s=COAT1.Product",
     "tags": {"weight_gain_pct": "ns=2;s=COAT1.WeightGain", "coat_inlet_c": "ns=2;s=COAT1.InletTemp", "exhaust_c": "ns=2;s=COAT1.ExhaustTemp",
              "spray_g_min": "ns=2;s=COAT1.SprayRate", "pan_rpm": "ns=2;s=COAT1.PanRPM", "atomizing_bar": "ns=2;s=COAT1.AtomizingBar"}},
]
PROFILE_BY_ID = {p["id"]: p for p in PROFILES}


def _norm(s: str) -> str:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s or "")  # camelCase → words, before lowercasing
    return re.sub(r"[^a-z0-9]+", " ", split.lower()).strip()


def suggest_mapping(type_id: str, tags: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{signal: {tag, name, score}} from browsed tags [{node, name, value}]: each signal's name hints matched against the
    tag's name (camelCase split), numeric tags only, each tag used once, the strongest match first. A suggestion the
    user confirms or changes — never applied silently."""
    t = TYPE_BY_ID.get(type_id)
    if not t:
        return {}
    scored = []
    for s in t["signals"]:
        rx = re.compile(s["hints"])
        for tag in tags:
            if not isinstance(tag.get("value"), (int, float)) or isinstance(tag.get("value"), bool):
                continue
            name = _norm(str(tag.get("name") or tag.get("node") or ""))
            m = rx.search(name)
            if m:
                scored.append((len(m.group(0)) / max(1, len(name)), s["id"], tag))
    out: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    for score, sid, tag in sorted(scored, key=lambda x: -x[0]):
        if sid not in out and tag["node"] not in used:
            out[sid] = {"tag": tag["node"], "name": tag.get("name"), "score": round(score, 2)}
            used.add(tag["node"])
    return out


def suggest_batch_tag(tags: list[dict[str, Any]]) -> Optional[str]:
    for tag in tags:
        if isinstance(tag.get("value"), str) and re.search(r"batch|lot", _norm(str(tag.get("name") or "")), re.I):
            return tag["node"]
    return None


def suggest_product_tag(tags: list[dict[str, Any]]) -> Optional[str]:
    for tag in tags:
        if isinstance(tag.get("value"), str) and re.search(r"product|recipe|item", _norm(str(tag.get("name") or "")), re.I):
            return tag["node"]
    return None
