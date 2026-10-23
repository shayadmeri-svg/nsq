"""Plant simulator for testing the Eurveda edge agent without a plant: an OPC UA server with five machines running
batches in sequence — rapid mixer granulator (RMG1) → fluid-bed dryer (FBD1) → blender (BLEND1) → tablet press
(PRESS1) → pan coater (COAT1) — two utilities running on their own (an autoclave, AUTOCLAVE1, cycling loads; a
cleanroom's HVAC, HVAC1), one machine of every other type in Connect's catalogue (sim_machines.json: sifter, mill,
blister line, purified-water loop, AHU, cold room, lyophiliser…), the AHU also over Siemens S7, and optionally the
press over Modbus TCP.

    python simulator.py                                       defaults from sim_defaults.json
    python simulator.py --config-url http://api:8001/api/ingest/plant-data/sim-config   settings from Eurveda (Sim engine)
    python simulator.py --modbus 5020                         also serve PRESS1 over Modbus TCP on port 5020

Every signal is setpoint + pattern + noise, clamped to its instrument range (min/max). Patterns:

    steady   setpoint ± noise
    drift    + amplitude per batch (e.g. compression force creeping up as punches wear)
    sine     + amplitude · sin(2π · minutes / period_min)
    step     + amplitude on every `every`-th batch (a recurring fault: every 3rd batch dried 21 min short)
    spikes   + amplitude on about one reading (or batch) in `every`
    ramp     rises by amplitude over each batch to the setpoint (e.g. impeller power as granules build)

Per-batch signals ("per": "batch") are drawn once when the batch starts (drying time, binder added, blend time).
The dryer's temperatures and LOD respond to the other inputs — more binder means more water to dry; short drying,
humid or cold air leave the LOD high — through illustrative couplings, not a model of any real machine.

With --config-url the settings are read from Eurveda every few seconds (Playground → Plant data → Live → Sim engine)
using the connector token in $EURVEDA_TOKEN; without it they come from sim_defaults.json.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import math
import os
import random
import re
import struct
import time
import urllib.request
from pathlib import Path
from typing import Any

from asyncua import Server, ua

log = logging.getLogger("sim")
HERE = Path(__file__).resolve().parent
ORDER = ["RMG-1", "FBD-1", "BLENDER-1", "PRESS-1", "COATER-1"]  # the order a batch goes through the plant
OBJECT = {"RMG-1": "RMG1", "FBD-1": "FBD1", "BLENDER-1": "BLEND1", "PRESS-1": "PRESS1", "COATER-1": "COAT1",
          "AUTOCLAVE-1": "AUTOCLAVE1", "HVAC-ROOM-1": "HVAC1"}
# OPC UA variable names (NodeId ns=2;s=<OBJECT>.<name>)
TAGS = {
    "RMG-1": {"dry_mix_kg": "DryMixKg", "binder_kg": "BinderKg", "wet_mix_min": "WetMixMin", "impeller_kw": "ImpellerKW"},
    "FBD-1": {"inlet_c": "InletTemp", "outlet_c": "OutletTemp", "product_c": "ProductTemp", "inlet_rh_pct": "InletRH",
              "air_m3_h": "AirFlow", "lod_pct": "LOD", "elapsed_min": "ElapsedMin"},
    "BLENDER-1": {"blend_min": "BlendMin", "blender_rpm": "SpeedRPM"},
    "PRESS-1": {"force_kn": "ForceKN", "precompression_kn": "PrecompKN", "tablet_weight_mg": "TabletWeightMg",
                "punch_diameter_mm": "PunchDiameterMm", "press_rpm": "TurretRPM"},
    "COATER-1": {"weight_gain_pct": "WeightGain", "coat_inlet_c": "InletTemp", "exhaust_c": "ExhaustTemp", "spray_g_min": "SprayRate",
                 "pan_rpm": "PanRPM", "atomizing_bar": "AtomizingBar"},
    "AUTOCLAVE-1": {"chamber_c": "ChamberTemp", "chamber_bar": "ChamberPressure", "f0_min": "F0"},
    "HVAC-ROOM-1": {"room_c": "RoomTemp", "room_rh_pct": "RoomRH", "dp_pa": "DiffPressure"},
}
# Modbus holding registers for PRESS1 (float32, big-endian words); batch number as ASCII at 20..27
MODBUS_MAP = {"force_kn": 0, "precompression_kn": 2, "tablet_weight_mg": 4, "punch_diameter_mm": 6, "press_rpm": 8}
MODBUS_BATCH = 20


def defaults() -> dict[str, Any]:
    return json.loads((HERE / "sim_defaults.json").read_text(encoding="utf-8"))


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Engine:
    def __init__(self, cfg: dict[str, Any], seed: int = 7):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.prefix = time.strftime("B%d%H%M-")  # batch numbers stay unique across restarts
        self.clock = 0.0  # simulated minutes since start
        self.n = 0  # newest batch started (index)
        self.t = 0.0  # minutes into the current takt
        self.draws: dict[int, dict[str, dict[str, float]]] = {}
        self.origin: dict[tuple[str, str], int] = {}  # where a drift pattern started
        self._takt()

    # --- configuration ---
    def apply(self, cfg: dict[str, Any]) -> None:
        for m, a in cfg.get("apparatus", {}).items():
            for f, s in a.get("signals", {}).items():
                was = self.cfg.get("apparatus", {}).get(m, {}).get("signals", {}).get(f, {}).get("pattern")
                if s.get("pattern") == "drift" and was != "drift":
                    self.origin[(m, f)] = self.n
        self.cfg = cfg

    def product(self, b: int) -> dict[str, Any]:
        ps = self.cfg.get("products") or [{"code": "", "label": "", "route": ORDER, "setpoints": {}}]
        return ps[(b - 1) % len(ps)]

    def on_route(self, m: str, b: int) -> bool:
        return m in (self.product(b).get("route") or ORDER)

    def sig(self, m: str, f: str, b: int = 0) -> dict[str, Any]:
        s = self.cfg["apparatus"][m]["signals"][f]
        off = ((self.product(b).get("offsets") or {}).get(m) or {}).get(f) if b else None  # the product's offset from the machine setpoint
        return {**s, "setpoint": float(s["setpoint"]) + float(off)} if off else s

    def value(self, m: str, f: str, b: int, progress: float = 1.0) -> float:
        s = self.sig(m, f, b)
        sp, amp, every = float(s["setpoint"]), float(s.get("amplitude", 0)), max(1, int(s.get("every", 3)))
        v, p = sp, s.get("pattern", "steady")
        if p == "drift":
            v += amp * (b - self.origin.get((m, f), b))
        elif p == "sine":
            v += amp * math.sin(2 * math.pi * self.clock / max(1.0, float(s.get("period_min", 60))))
        elif p == "step" and b % every == 0:
            v += amp
        elif p == "ramp":
            v -= amp * (1 - min(1.0, max(0.0, progress)))
        elif p == "spikes" and self.rng.random() < 1 / every:
            v += amp
        v += self.rng.gauss(0, float(s.get("noise", 0)))
        return min(float(s.get("max", v)), max(float(s.get("min", v)), v))

    # --- batches ---
    def _draw(self, b: int) -> None:
        d: dict[str, dict[str, float]] = {}
        for m, a in self.cfg["apparatus"].items():
            d[m] = {f: self.value(m, f, b, 0.0) for f, s in a["signals"].items() if s.get("per") == "batch"}
        rmg = d.get("RMG-1", {})
        liquid = 100 * rmg.get("binder_kg", 25) / max(1e-6, rmg.get("dry_mix_kg", 100))
        fbd = self.cfg["apparatus"]["FBD-1"]["signals"]
        T = d["FBD-1"]["drying_min"]
        need = 60 * liquid / 25  # minutes the water load needs at the reference air
        d["FBD-1"]["_final_lod"] = max(0.4, float(self.product(b).get("lod_base", 1.6)) + 0.09 * max(0.0, need - T) + 0.06 * max(0.0, float(fbd["inlet_rh_pct"]["setpoint"]) - 8)
                                       + 0.05 * max(0.0, 60 - float(fbd["inlet_c"]["setpoint"])) + 0.0006 * max(0.0, 3000 - float(fbd["air_m3_h"]["setpoint"]))
                                       + self.rng.gauss(0, 0.1))
        d["FBD-1"]["_liquid"] = liquid
        self.draws[b] = d
        for old in [k for k in self.draws if k < b - 8]:
            del self.draws[old]

    def duration(self, m: str, b: int) -> float:
        a = self.cfg["apparatus"][m]
        if m == "FBD-1":
            return self.draws[b]["FBD-1"]["drying_min"]
        if m == "BLENDER-1":
            return max(float(a.get("duration_min", 10)), self.draws[b]["BLENDER-1"]["blend_min"])
        return float(a.get("duration_min", 30))

    def _takt(self) -> None:
        self.n += 1
        self._draw(self.n)
        live = [self.duration(m, self.n - k) for k, m in enumerate(ORDER)
                if m in self.cfg["apparatus"] and self.cfg["apparatus"][m].get("enabled", True) and self.n - k >= 1 and self.on_route(m, self.n - k)]
        self.takt = max(live or [10.0]) + float(self.cfg.get("handling_min", 5))
        self.t = 0.0

    def step(self, sim_min: float) -> None:
        if not self.cfg.get("running", True):
            return
        self.clock += sim_min
        self.t += sim_min
        if self.t >= self.takt:
            self._takt()

    def readings(self) -> dict[str, tuple[str, dict[str, float]]]:
        """{machine: (batch number, or "" when idle, {field: value}, product label)}"""
        out = {}
        for k, m in enumerate(ORDER):
            b = self.n - k
            a = self.cfg["apparatus"].get(m)
            if a is None:
                continue
            running = a.get("enabled", True) and b >= 1 and self.on_route(m, b) and self.t <= self.duration(m, b)
            if not running:
                out[m] = ("", self._idle(m), "")
                continue
            pr = self.t / max(1e-6, self.duration(m, b))
            d = self.draws[b][m]
            vals = {f: (d[f] if s.get("per") == "batch" else self.value(m, f, b, pr)) for f, s in a["signals"].items()}
            if m == "FBD-1":
                T, t, inlet = d["drying_min"], self.t, vals["inlet_c"]
                vals = {"inlet_c": inlet, "inlet_rh_pct": vals["inlet_rh_pct"], "air_m3_h": vals["air_m3_h"],
                        "outlet_c": inlet / 60 * (30 + 0.25 * t) + self.rng.gauss(0, 0.4), "product_c": inlet / 60 * (28 + 0.27 * t) + self.rng.gauss(0, 0.4),
                        "lod_pct": d["_final_lod"] + max(0.0, 1 - t / T) * 18 * d["_liquid"] / 25 + self.rng.gauss(0, 0.05), "elapsed_min": round(t, 2)}
            elif m == "COATER-1":  # weight gain builds up to the batch's target over the coating time
                vals["weight_gain_pct"] = d["weight_gain_pct"] * pr + self.rng.gauss(0, 0.02)
            p = self.product(b)
            out[m] = (f"{p.get('code', '')[:3]}{self.prefix}{b:03d}", {f: v for f, v in vals.items() if f in TAGS[m]}, p.get("code", ""))
        return out

    @staticmethod
    def _idle(m: str) -> dict[str, float]:
        return {"FBD-1": {"inlet_c": 31.0, "outlet_c": 29.0, "product_c": 28.0, "inlet_rh_pct": 55.0, "air_m3_h": 0.0, "lod_pct": 0.0, "elapsed_min": 0.0},
                "PRESS-1": {"force_kn": 0.0, "precompression_kn": 0.0, "tablet_weight_mg": 0.0, "punch_diameter_mm": 12.0, "press_rpm": 0.0},
                "RMG-1": {"dry_mix_kg": 0.0, "binder_kg": 0.0, "wet_mix_min": 0.0, "impeller_kw": 0.0},
                "BLENDER-1": {"blend_min": 0.0, "blender_rpm": 0.0},
                "COATER-1": {"weight_gain_pct": 0.0, "coat_inlet_c": 30.0, "exhaust_c": 29.0, "spray_g_min": 0.0, "pan_rpm": 0.0, "atomizing_bar": 0.0}}[m]


# A plant's other machines (sim_machines.json, exported from Connect's catalogue): each signal swings slowly around a
# working point inside its typical range, with noise; batch machines number a batch every hour of simulated time.
# Working points where the middle of the range would be wrong for a pharma plant:
WORKING_POINT = {("cold_room", "temp_c"): 5.0, ("cold_room", "door_open"): 0.0, ("stability_chamber", "chamber_c"): 25.0,
                 ("stability_chamber", "chamber_rh_pct"): 60.0, ("pw_system", "conductivity_us_cm"): 0.6, ("pw_system", "toc_ppb"): 120.0,
                 ("pw_system", "loop_c"): 80.0, ("dissolution_tester", "bath_c"): 37.0, ("dissolution_tester", "rpm"): 50.0,
                 ("compressed_air", "dew_point_c"): -40.0, ("compressed_air", "pressure_bar"): 7.0, ("lyophilizer", "shelf_c"): -40.0,
                 ("lyophilizer", "product_c"): -42.0, ("lyophilizer", "chamber_ubar"): 100.0, ("lyophilizer", "condenser_c"): -70.0,
                 ("isolator", "h2o2_ppm"): 0.5, ("isolator", "particles_05_m3"): 300.0, ("particle_counter", "particles_05_m3"): 2000.0,
                 ("particle_counter", "particles_5_m3"): 20.0, ("depyrogenation_tunnel", "hot_zone_c"): 300.0, ("chiller", "supply_c"): 7.0,
                 ("chiller", "return_c"): 12.0, ("hplc", "assay_pct"): 99.5, ("hplc", "impurity_pct"): 0.12}


class Generic:
    def __init__(self, spec: dict[str, Any], rng: random.Random, prefix: str):
        self.spec, self.rng, self.prefix = spec, rng, prefix
        self.phase = rng.random() * 6.28

    def readings(self, clock: float) -> tuple[str, dict[str, float], str]:
        vals = {}
        for sg in self.spec["signals"]:
            lo, hi = (float(x) for x in sg["typical"])
            span = hi - lo
            wp = WORKING_POINT.get((self.spec["type"], sg["field"]))
            if wp is None:
                wp = lo + (0.1 if "count" in sg["var"].lower() or sg["field"] in ("rejects",) else 0.45) * span
            if sg["field"] == "door_open":
                vals[sg["field"]] = 1.0 if self.rng.random() < 0.01 else 0.0
                continue
            v = wp + 0.04 * span * math.sin(2 * math.pi * clock / 180 + self.phase) + self.rng.gauss(0, 0.008 * span)
            vals[sg["field"]] = min(hi, max(lo, v))
        batch = f"{self.spec['object'][:3]}{self.prefix}{int(clock // 60) + 1:03d}" if self.spec["batch"] else ""
        return batch, vals, ""


def sim_machines() -> dict[str, Any]:
    p = HERE / "sim_machines.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"machines": []}


def start_s7(port: int, size: int):
    """Serve DB1 over Siemens S7 (python-snap7's server); the AHU's values are written into it as REALs."""
    from snap7 import server as s7server
    from snap7.type import SrvArea

    srv = s7server.Server()
    db = bytearray(size)
    srv.register_area(SrvArea.DB, 1, db)
    srv.start(tcp_port=port)
    return srv, db


class Utilities:
    """The autoclave and the room's HVAC: not on the batch route, running on the simulated clock.

    Autoclave: load after load — heat-up to 121.5 °C (15 min), exposure (15 min), exhaust and cool (15 min), unloading
    (5 min). Chamber pressure is saturated steam's (Antoine equation for water), as gauge pressure; F0 is the lethality
    accumulated over the cycle, ∫10^((T − 121.1)/10) dt. Every 4th load holds 0.9 °C low during exposure (a recurring
    steam-supply fault, F0 short). Room: temperature and humidity swing slowly around 22 °C / 45 %RH; the pressure
    differential to the corridor dips when a door opens. Illustrative, as the line's couplings are."""

    CYCLE = (("heat", 15.0), ("exposure", 15.0), ("exhaust", 15.0), ("unload", 5.0))

    def __init__(self, rng: random.Random, prefix: str):
        self.rng, self.prefix = rng, prefix
        self.load, self.t, self.f0, self.last = 1, 0.0, 0.0, 0.0
        self.door = 0.0

    def step(self, clock: float) -> None:
        dt, self.last = clock - self.last, clock
        self.t += dt
        if self.t >= sum(d for _, d in self.CYCLE):
            self.load, self.t, self.f0 = self.load + 1, 0.0, 0.0
        self.f0 += 10 ** ((self._chamber() - 121.1) / 10) * dt
        self.door = max(0.0, self.door - dt) if self.door else (1.5 if self.rng.random() < 0.004 else 0.0)

    def _phase(self) -> tuple[str, float]:
        t = self.t
        for name, d in self.CYCLE:
            if t < d:
                return name, t / d
            t -= d
        return "unload", 1.0

    def _chamber(self) -> float:
        phase, f = self._phase()
        hold = 121.5 - (0.9 if self.load % 4 == 0 else 0.0)
        return {"heat": 25 + (hold - 25) * f, "exposure": hold, "exhaust": hold - (hold - 45) * f, "unload": 45 - 15 * f}[phase]

    def readings(self, clock: float) -> dict[str, tuple[str, dict[str, float], str]]:
        T = self._chamber() + self.rng.gauss(0, 0.15)
        p_abs = 10 ** (8.14019 - 1810.94 / (244.485 + T)) * 0.00133322 if T >= 100 else 1.013  # mmHg → bar
        phase, _ = self._phase()
        load = f"AC{self.prefix}{self.load:03d}" if phase != "unload" else ""
        cyc = 2 * math.pi * clock / 240
        return {
            "AUTOCLAVE-1": (load, {"chamber_c": T, "chamber_bar": max(0.0, p_abs - 1.013 + self.rng.gauss(0, 0.005)), "f0_min": self.f0}, ""),
            "HVAC-ROOM-1": ("", {"room_c": 22 + 0.6 * math.sin(cyc) + self.rng.gauss(0, 0.08),
                                 "room_rh_pct": 45 + 4 * math.sin(cyc + 1.1) + self.rng.gauss(0, 0.3),
                                 "dp_pa": (3.0 if self.door else 15.0) + self.rng.gauss(0, 0.6)}, ""),
        }


def fetch_config(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "x-nsq-client": "simulator"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())["config"]


class Registers:
    """Holding registers of a minimal Modbus TCP server (function 3, read holding registers — all the agent uses)."""

    def __init__(self, n: int = 64):
        self.r = [0] * n

    def set(self, at: int, values: list[int]) -> None:
        self.r[at:at + len(values)] = values


async def start_modbus(port: int) -> Registers:
    """Serve PRESS1 over Modbus TCP: MBAP header + PDU, function 3 only (others answer 'illegal function')."""
    regs = Registers()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                tid, _proto, length, unit = struct.unpack(">HHHB", await reader.readexactly(7))
                pdu = await reader.readexactly(length - 1)
                fc = pdu[0]
                if fc == 3 and len(pdu) >= 5:
                    at, count = struct.unpack(">HH", pdu[1:5])
                    body = (struct.pack(">BB", fc | 0x80, 2) if at + count > len(regs.r) or count == 0
                            else struct.pack(">BB", fc, 2 * count) + struct.pack(f">{count}H", *regs.r[at:at + count]))
                else:
                    body = struct.pack(">BB", fc | 0x80, 1)
                writer.write(struct.pack(">HHHB", tid, 0, len(body) + 1, unit) + body)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()

    await asyncio.start_server(handle, "0.0.0.0", port)
    return regs


async def main(a: argparse.Namespace) -> None:
    base = defaults()
    if a.speed:
        base["speed"] = a.speed
    sig = base["apparatus"]
    if a.fault != "short-dry":
        sig["FBD-1"]["signals"]["drying_min"]["pattern"] = "steady"
    if a.fault == "over-compress":
        sig["PRESS-1"]["signals"]["force_kn"].update(pattern="step", amplitude=5.5, every=a.fault_every)
    elif a.fault == "humid-air":
        sig["FBD-1"]["signals"]["inlet_rh_pct"].update(pattern="step", amplitude=17, every=a.fault_every)
    elif a.fault == "short-dry":
        sig["FBD-1"]["signals"]["drying_min"]["every"] = a.fault_every
    eng = Engine(base, a.seed)
    util = Utilities(random.Random(a.seed + 1), eng.prefix)

    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://0.0.0.0:{a.port}/eurveda-sim/")
    server.set_server_name("Eurveda plant simulator")
    idx = await server.register_namespace("urn:eurveda:sim")
    nodes: dict[str, dict[str, Any]] = {}
    for m, obj_name in OBJECT.items():
        obj = await server.nodes.objects.add_object(ua.NodeId(obj_name, idx), ua.QualifiedName(obj_name, idx))
        nodes[m] = {f: await obj.add_variable(ua.NodeId(f"{obj_name}.{tag}", idx), ua.QualifiedName(tag, idx), 0.0) for f, tag in TAGS[m].items()}
        nodes[m]["_batch"] = await obj.add_variable(ua.NodeId(f"{obj_name}.BatchNo", idx), ua.QualifiedName("BatchNo", idx), "")
        nodes[m]["_product"] = await obj.add_variable(ua.NodeId(f"{obj_name}.Product", idx), ua.QualifiedName("Product", idx), "")
    extra = sim_machines()
    generic = {m["name"]: Generic(m, random.Random(a.seed + i + 2), eng.prefix) for i, m in enumerate(extra["machines"])}
    by_obj: dict[str, str] = {OBJECT[m]: m for m in OBJECT}  # simulated object → the key its nodes are under

    async def serve(key: str, obj_name: str, fields: dict[str, str]) -> None:
        """Add an object with a variable per signal (and BatchNo, Product) — at start, or when Connect adds a machine."""
        obj = await server.nodes.objects.add_object(ua.NodeId(obj_name, idx), ua.QualifiedName(obj_name, idx))
        nodes[key] = {f: await obj.add_variable(ua.NodeId(f"{obj_name}.{v}", idx), ua.QualifiedName(v, idx), 0.0) for f, v in fields.items()}
        nodes[key]["_batch"] = await obj.add_variable(ua.NodeId(f"{obj_name}.BatchNo", idx), ua.QualifiedName("BatchNo", idx), "")
        nodes[key]["_product"] = await obj.add_variable(ua.NodeId(f"{obj_name}.Product", idx), ua.QualifiedName("Product", idx), "")
        by_obj[obj_name] = key

    for m in extra["machines"]:
        await serve(m["name"], m["object"], {sg["field"]: sg["var"] for sg in m["signals"]})
    connected: dict[str, str] = {}  # machines set up in Connect (Sim engine "extra" apparatus) → the key their nodes are under
    s7 = extra.get("s7")
    s7_machine = next((m for m in extra["machines"] if s7 and m["type"] == s7["type"]), None)
    s7db = None
    if s7_machine and a.s7:
        try:
            _s7srv, s7db = start_s7(int(s7["port"]), 4 * len(s7_machine["signals"]))
            log.info("Siemens S7 on :%s (DB1: %s)", s7["port"], ", ".join(sg["field"] for sg in s7_machine["signals"]))
        except Exception as exc:  # noqa: BLE001 — OPC UA keeps working without it
            log.warning("S7 server not started: %s", exc)
    regs = await start_modbus(a.modbus) if a.modbus else None
    token = os.environ.get(a.token_env, "")
    last_fetch = 0.0
    async with server:
        log.info("OPC UA on opc.tcp://localhost:%d/eurveda-sim/ (namespace %d)%s; settings from %s", a.port, idx,
                 f", Modbus on :{a.modbus}" if a.modbus else "", a.config_url or "sim_defaults.json")
        while True:
            if a.config_url and token and time.monotonic() - last_fetch > a.config_every:
                last_fetch = time.monotonic()
                try:
                    cfg = await asyncio.get_running_loop().run_in_executor(None, fetch_config, a.config_url, token)
                    eng.apply(merge(base, cfg))
                except Exception as exc:  # noqa: BLE001 — keep simulating with the last settings
                    log.warning("could not read settings from Eurveda: %s", exc)
            for name, ap in eng.cfg.get("apparatus", {}).items():  # a machine added in Connect: serve it under its own name
                if ap.get("extra") and name not in connected:
                    obj_name = re.sub(r"[^A-Za-z0-9]", "", name).upper()
                    if obj_name in by_obj:  # the simulator already serves this object (e.g. SIFTER-1): Sim engine settings now drive it
                        generic.pop(by_obj[obj_name], None)
                        connected[name] = by_obj[obj_name]
                    else:
                        await serve(name, obj_name, {f: sg.get("var") or "".join(w[:1].upper() + w[1:] for w in f.split("_")) for f, sg in ap["signals"].items()})
                        connected[name] = name
                    log.info("serving %s as %s", name, obj_name)
            eng.step(float(eng.cfg.get("speed", 30)) / 60.0)
            util.step(eng.clock)
            every = {**eng.readings(), **util.readings(eng.clock), **{n: g.readings(eng.clock) for n, g in generic.items()}}
            for name, key in connected.items():
                ap = eng.cfg["apparatus"].get(name)
                if not ap or not ap.get("enabled", True):
                    continue
                b = eng.n
                prod = eng.product(b)
                batch = f"{prod.get('code', '')[:3]}{eng.prefix}{b:03d}" if ap.get("batch") else ""
                every[key] = (batch, {f: eng.value(name, f, b, min(1.0, eng.t / max(1e-6, eng.takt))) for f in ap["signals"]},
                              prod.get("code", "") if ap.get("batch") else "")
            if s7db is not None:
                for i, sg in enumerate(s7_machine["signals"]):
                    s7db[4 * i:4 * i + 4] = struct.pack(">f", float(every[s7_machine["name"]][1][sg["field"]]))
            for m, (batch, vals, product) in every.items():
                for f, v in vals.items():
                    await nodes[m][f].write_value(float(v))
                await nodes[m]["_batch"].write_value(batch)
                await nodes[m]["_product"].write_value(product)
                if regs is not None and m == "PRESS-1":
                    for f, at in MODBUS_MAP.items():
                        regs.set(at, list(struct.unpack(">HH", struct.pack(">f", float(vals.get(f, 0.0))))))
                    regs.set(MODBUS_BATCH, list(struct.unpack(">8H", batch.encode("ascii").ljust(16, b"\x00")[:16])))
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4840)
    ap.add_argument("--modbus", type=int, default=0, help="also serve PRESS1 over Modbus TCP on this port")
    ap.add_argument("--no-s7", dest="s7", action="store_false", help="do not serve the AHU over Siemens S7 (port in sim_machines.json)")
    ap.add_argument("--speed", type=float, default=0, help="simulated seconds per real second (default from the settings: 30)")
    ap.add_argument("--fault", choices=["none", "short-dry", "over-compress", "humid-air"], default="short-dry",
                    help="starting pattern without --config-url (default: every 3rd batch dried 21 min short)")
    ap.add_argument("--fault-every", type=int, default=3)
    ap.add_argument("--config-url", default="", help="read settings from Eurveda (…/api/ingest/plant-data/sim-config)")
    ap.add_argument("--config-every", type=float, default=5.0, help="seconds between reads of the settings")
    ap.add_argument("--token-env", default="EURVEDA_TOKEN")
    ap.add_argument("--seed", type=int, default=7)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    asyncio.run(main(ap.parse_args()))
