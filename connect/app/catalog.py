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

from .equipment import AREAS, EQUIPMENT_TYPES, TYPE_BY_ID  # noqa: E402,F401  (re-exported)

# `agent`: the edge agent reads it (test read works). `tag`: what one signal's address looks like, and `tag_rx` the
# check made when a machine is saved (a typo is reported there, not as a failed read at the plant).
PROTOCOLS: list[dict[str, Any]] = [
    {"id": "opcua", "label": "OPC UA", "status": "available", "kind": "machine", "agent": True,
     "what": "Modern PLCs, SCADA and most new machines. Read-only, browsable tags.",
     "tag": "ns=2;s=FBD1.InletTemp", "tag_rx": r"^(ns=\d+;|nsu=[^;]+;)?(i=\d+|s=.+|g=[0-9a-fA-F-]{36}|b=.+)$",
     "fields": [{"id": "endpoint", "label": "Endpoint", "placeholder": "opc.tcp://10.0.0.20:4840", "required": True},
                {"id": "security", "label": "Security", "placeholder": "Basic256Sha256,SignAndEncrypt,cert.der,key.pem"},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "modbus_tcp", "label": "Modbus TCP", "status": "available", "kind": "machine", "agent": True,
     "what": "Older panels, dryers, utilities, meters. Register addresses from the machine's manual.",
     "tag": "40001:float32  ·  hr100:int16*0.1  ·  ir5:uint16  ·  40021:string16",
     "tag_rx": r"^(hr|ir|[34])?\d+(:(float32|int32|uint32|int16|uint16|string\d+))?(:(big|little))?(\*-?[\d.]+)?$",
     "fields": [{"id": "host", "label": "Host", "placeholder": "192.168.1.30", "required": True},
                {"id": "port", "label": "Port", "placeholder": "502"}, {"id": "unit", "label": "Unit id", "placeholder": "1"},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "s7", "label": "Siemens S7", "status": "available", "kind": "machine", "agent": True,
     "what": "S7-300/400/1200/1500 PLCs read directly (ISO-on-TCP, python-snap7): no OPC UA server needed. "
             "On S7-1200/1500, allow PUT/GET and use non-optimised data blocks.",
     "tag": "DB1.DBD0:REAL  ·  DB10.DBW4:INT  ·  DB1.DBX2.1:BOOL  ·  MD100:REAL  ·  DB2.DBB0:STRING20",
     "tag_rx": r"^(DB\d+\.DB[BWDX]\d+(\.\d)?|[MIQE][BWDX]?\d+(\.\d)?)(:(REAL|LREAL|INT|DINT|WORD|DWORD|BYTE|BOOL|STRING\d*))?(\*-?[\d.]+)?$",
     "fields": [{"id": "host", "label": "PLC address", "placeholder": "192.168.0.1", "required": True},
                {"id": "rack", "label": "Rack", "placeholder": "0"}, {"id": "slot", "label": "Slot", "placeholder": "1 (S7-1200/1500: 1; S7-300: 2)"},
                {"id": "port", "label": "Port", "placeholder": "102"}, {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "ethernet_ip", "label": "Rockwell EtherNet/IP", "status": "beta", "kind": "machine", "agent": True,
     "what": "Allen-Bradley ControlLogix / CompactLogix tags by name (CIP, pycomm3).",
     "tag": "Dryer_InletTemp  ·  Program:Main.LOD  ·  Recipe.BatchNo", "tag_rx": r"^[A-Za-z_][\w:.\[\]]*$",
     "fields": [{"id": "host", "label": "Controller path", "placeholder": "192.168.1.10 or 192.168.1.10/0", "required": True},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "modbus_rtu", "label": "Modbus RTU (RS-485)", "status": "beta", "kind": "machine", "agent": True,
     "what": "Serial meters, controllers and older panels on an RS-485 line (USB adapter on the agent's PC).",
     "tag": "40001:float32  ·  hr100:int16*0.1", "tag_rx": r"^(hr|ir|[34])?\d+(:(float32|int32|uint32|int16|uint16|string\d+))?(:(big|little))?(\*-?[\d.]+)?$",
     "fields": [{"id": "serial_port", "label": "Serial port", "placeholder": "/dev/ttyUSB0 or COM3", "required": True},
                {"id": "baudrate", "label": "Baud rate", "placeholder": "9600"}, {"id": "parity", "label": "Parity", "placeholder": "N, E or O"},
                {"id": "unit", "label": "Unit id", "placeholder": "1"}, {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "mqtt", "label": "MQTT", "status": "beta", "kind": "machine", "agent": True,
     "what": "IoT gateways and edge boxes publishing to a broker: a topic per value, or JSON with a path to the value.",
     "tag": "plant/fbd1/inlet_temp  ·  plant/fbd1/state|inlet.temp", "tag_rx": r"^[^#+|]+(\|[\w.\[\]-]+)?$",
     "fields": [{"id": "broker", "label": "Broker", "placeholder": "mqtt://10.0.0.5:1883 (mqtts:// for TLS)", "required": True},
                {"id": "username", "label": "User"}, {"id": "password_env", "label": "Password from env var", "placeholder": "MQTT_PASSWORD"}]},
    {"id": "rest", "label": "HTTP / REST (incl. PI Web API)", "status": "beta", "kind": "system", "agent": True,
     "what": "A JSON endpoint polled by the agent: gateways (Kepware IoT Gateway), building systems, or AVEVA PI Web API "
             "(tag = the point's WebId).",
     "tag": "data.inlet_temp  ·  values[0].v  ·  (PI) F1DPm0SX…", "tag_rx": r"^[\w.\[\]-]+$",
     "fields": [{"id": "url", "label": "URL", "placeholder": "https://gw.plant/api/values  or  https://pi/piwebapi", "required": True},
                {"id": "mode", "label": "Mode", "placeholder": "json (default) or pi"},
                {"id": "auth_env", "label": "Auth from env var", "placeholder": "PI_AUTH (user:password or a bearer token)"},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "10"}]},
    {"id": "sql", "label": "SQL historian", "status": "beta", "kind": "system", "agent": True,
     "what": "Historians that keep values in SQL (AVEVA Historian, Wonderware, SCADA logs in SQL Server, PostgreSQL, "
             "MySQL): one query returns a tag's latest value.",
     "tag": "the tag name, passed to the query as :tag", "tag_rx": r"^.+$",
     "fields": [{"id": "dsn_env", "label": "Connection from env var", "placeholder": "HISTORIAN_DSN (mssql+pymssql://…)", "required": True},
                {"id": "query", "label": "Query", "placeholder": "SELECT TOP 1 Value FROM History WHERE TagName = :tag ORDER BY DateTime DESC"},
                {"id": "poll_s", "label": "Poll every (s)", "placeholder": "30"}]},
    {"id": "serial_ascii", "label": "Serial balance (RS-232)", "status": "beta", "kind": "machine", "agent": True,
     "what": "Balances and scales that answer a text command: Mettler-Toledo MT-SICS (SI), Sartorius SBI (ESC P), "
             "and similar.",
     "tag": "SI  ·  S  ·  ESC P   (the command; the first number in the reply is read)", "tag_rx": r"^.{1,20}$",
     "fields": [{"id": "serial_port", "label": "Serial port", "placeholder": "/dev/ttyUSB0 or COM3", "required": True},
                {"id": "baudrate", "label": "Baud rate", "placeholder": "9600"}, {"id": "poll_s", "label": "Poll every (s)", "placeholder": "5"}]},
    {"id": "bacnet", "label": "BACnet/IP", "status": "planned", "kind": "machine",
     "what": "Building management and HVAC controllers (AHUs, chillers, room sensors).", "fields": []},
    {"id": "opc_da", "label": "OPC DA (classic)", "status": "planned", "kind": "machine",
     "what": "Older Windows SCADA servers (DCOM): read through an OPC UA wrapper or gateway on the SCADA PC.", "fields": []},
    {"id": "ebmr", "label": "eBMR / LIMS export", "status": "planned", "kind": "system",
     "what": "Batch records and QC results from AmpleLogic-, Caliber-type systems (API or scheduled export).", "fields": []},
    {"id": "file", "label": "File drop (CSV / Excel)", "status": "available", "kind": "file",
     "what": "Exports from any machine or system, uploaded or dropped in a watched folder.", "fields": []},
    {"id": "manual", "label": "Manual entry", "status": "available", "kind": "file",
     "what": "Paper-based steps: the operator types readings on a tablet.", "fields": []},
]
PROTOCOL_BY_ID = {p["id"]: p for p in PROTOCOLS}
DOSAGE_FORMS = ["tablet", "film-coated tablet", "capsule", "oral liquid", "ointment / cream", "injectable"]


def _camel(field: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in field.split("_"))


def sim_object(type_id: str) -> str:
    """The simulator's object for a type: SIFTER1, PW_SYSTEM → PWSYSTEM1."""
    return type_id.upper().replace("_", "") + "1"


# The line's machines and the two utilities keep their own simulator names; every other type has a generic one
# (edge-agent/simulator.py serves all of them, each signal named after its field id in CamelCase).
_SIM_NAMED = {
    "rmg": ("RMG1", {"binder_kg": "BinderKg", "dry_mix_kg": "DryMixKg", "wet_mix_min": "WetMixMin", "impeller_kw": "ImpellerKW"}),
    "fbd": ("FBD1", {"inlet_c": "InletTemp", "outlet_c": "OutletTemp", "product_c": "ProductTemp", "inlet_rh_pct": "InletRH",
                     "air_m3_h": "AirFlow", "lod_pct": "LOD", "elapsed_min": "ElapsedMin"}),
    "blender": ("BLEND1", {"blend_min": "BlendMin", "blender_rpm": "SpeedRPM"}),
    "press": ("PRESS1", {"force_kn": "ForceKN", "precompression_kn": "PrecompKN", "tablet_weight_mg": "TabletWeightMg",
                         "punch_diameter_mm": "PunchDiameterMm", "press_rpm": "TurretRPM"}),
    "coater": ("COAT1", {"weight_gain_pct": "WeightGain", "coat_inlet_c": "InletTemp", "exhaust_c": "ExhaustTemp",
                         "spray_g_min": "SprayRate", "pan_rpm": "PanRPM", "atomizing_bar": "AtomizingBar"}),
    "autoclave": ("AUTOCLAVE1", {"chamber_c": "ChamberTemp", "chamber_bar": "ChamberPressure", "f0_min": "F0"}),
    "hvac_room": ("HVAC1", {"room_c": "RoomTemp", "room_rh_pct": "RoomRH", "dp_pa": "DiffPressure"}),
}


def sim_tags(type_id: str) -> tuple[str, dict[str, str]]:
    """(object, {field: variable}) the simulator serves for a type."""
    if type_id in _SIM_NAMED:
        return _SIM_NAMED[type_id]
    return sim_object(type_id), {s["id"]: _camel(s["id"]) for s in TYPE_BY_ID[type_id]["signals"]}


def _sim_profile(t: dict[str, Any]) -> dict[str, Any]:
    obj, tags = sim_tags(t["id"])
    return {"id": f"eurveda-sim-{t['id'].replace('_', '-')}", "label": f"Eurveda plant simulator · {obj}", "type": t["id"], "protocol": "opcua",
            "verified": "simulator", "batch_tag": f"ns=2;s={obj}.BatchNo" if t["batch"] else "",
            "product_tag": f"ns=2;s={obj}.Product" if t["batch"] else "", "tags": {f: f"ns=2;s={obj}.{v}" for f, v in tags.items()}}


# The simulator's AHU is also served over Siemens S7 (DB1, one REAL per signal, 4 bytes apart, in signal order),
# so the S7 path can be tried end to end.
S7_SIM = {"type": "ahu", "db": 1, "port": 1102}


def _s7_profile() -> dict[str, Any]:
    t = TYPE_BY_ID[S7_SIM["type"]]
    return {"id": "eurveda-sim-ahu-s7", "label": "Eurveda plant simulator · AHU1 over Siemens S7", "type": t["id"], "protocol": "s7",
            "verified": "simulator", "batch_tag": "", "product_tag": "",
            "tags": {s["id"]: f"DB{S7_SIM['db']}.DBD{4 * i}:REAL" for i, s in enumerate(t["signals"])}}


# Machine-model tag maps, verified against the machine they describe (protocol, type, {signal: tag}). The simulator's
# models are generated (one per type); OEM models are added from a real machine during onboarding.
PROFILES: list[dict[str, Any]] = [_sim_profile(t) for t in EQUIPMENT_TYPES] + [_s7_profile()]
# the ids plants already saved for the line's machines
for _old, _new in (("eurveda-sim-rmg", "rmg"), ("eurveda-sim-fbd", "fbd"), ("eurveda-sim-blender", "blender"),
                   ("eurveda-sim-press", "press"), ("eurveda-sim-coater", "coater"), ("eurveda-sim-hvac", "hvac_room")):
    if not any(p["id"] == _old for p in PROFILES):
        PROFILES.append({**_sim_profile(TYPE_BY_ID[_new]), "id": _old, "hidden": True})
PROFILE_BY_ID = {p["id"]: p for p in PROFILES}


# the simulator's own names for its original machines; any other machine is served under its name without symbols
SIM_BUILTIN = {"RMG-1": "RMG1", "FBD-1": "FBD1", "BLENDER-1": "BLEND1", "PRESS-1": "PRESS1", "COATER-1": "COAT1",
               "AUTOCLAVE-1": "AUTOCLAVE1", "HVAC-ROOM-1": "HVAC1"}


def sim_object_for(machine_name: str) -> str:
    return SIM_BUILTIN.get(machine_name) or re.sub(r"[^A-Za-z0-9]", "", machine_name).upper()


def retarget(profile: dict[str, Any], machine_name: str) -> dict[str, Any]:
    """A simulator machine model, pointed at this machine's own simulated object (RMG-2 → ns=2;s=RMG2.BinderKg):
    the simulator serves every machine set up in Connect under its own name. Built-in names keep their objects; any
    other machine's variables are its signal ids in CamelCase."""
    if profile.get("verified") != "simulator" or profile["protocol"] != "opcua":
        return profile
    obj = sim_object_for(machine_name)
    builtin = obj in SIM_BUILTIN.values()
    t = TYPE_BY_ID[profile["type"]]
    tags = ({f: v.replace(v.split(";s=", 1)[1].split(".", 1)[0], obj, 1) for f, v in profile["tags"].items()} if builtin and obj == sim_tags(t["id"])[0]
            else {s["id"]: f"ns=2;s={obj}.{_camel(s['id'])}" for s in t["signals"]})
    if builtin and obj != sim_tags(t["id"])[0]:  # a built-in name on another type (unlikely): generic variables
        tags = {s["id"]: f"ns=2;s={obj}.{_camel(s['id'])}" for s in t["signals"]}
    return {**profile, "tags": tags, "batch_tag": f"ns=2;s={obj}.BatchNo" if t["batch"] else "",
            "product_tag": f"ns=2;s={obj}.Product" if t["batch"] else ""}


def bad_tags(protocol: str, tags: dict[str, Any]) -> list[str]:
    """The entries of {field: address} that are not addresses in this protocol's syntax."""
    rx = PROTOCOL_BY_ID.get(protocol, {}).get("tag_rx")
    if not rx:
        return []
    r = re.compile(rx, re.I if protocol in ("modbus_tcp", "modbus_rtu", "s7") else 0)
    return [f"{k} = {v!r}" for k, v in tags.items() if v not in (None, "") and not r.match(str(v).strip())]


def bad_node_ids(tags: dict[str, Any]) -> list[str]:
    return bad_tags("opcua", tags)


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
