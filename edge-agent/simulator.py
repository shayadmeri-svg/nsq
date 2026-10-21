"""Plant simulator for testing the Eurveda edge agent without a plant: an OPC UA server with a fluid-bed dryer (FBD1)
and a tablet press (PRESS1) running batch after batch, and optionally the same press over Modbus TCP.

    python simulator.py                                    OPC UA on opc.tcp://0.0.0.0:4840/eurveda-sim/
    python simulator.py --speed 60 --fault short-dry --fault-every 3
    python simulator.py --modbus 5020                      also serve PRESS1 over Modbus TCP on port 5020

Simulated time runs `--speed` times faster than real time (default 30: a 60-minute drying takes 2 minutes). The dryer
dries batch N while the press compresses batch N-1. Every `--fault-every`-th batch carries the chosen fault:

    short-dry       the dryer stops at 39 min instead of 60 (loss on drying ends high)
    over-compress   main compression force 18.5 kN instead of 13 (slow disintegration)
    humid-air       inlet air at 25 %RH instead of 8 (less drying capacity)

The numbers are illustrative, for exercising the pipeline; they are not a model of any real machine.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
import struct
import time

from asyncua import Server, ua

log = logging.getLogger("sim")

FBD_TAGS = {"InletTemp": 60.0, "OutletTemp": 30.0, "ProductTemp": 28.0, "InletRH": 8.0, "AirFlow": 3000.0, "LOD": 20.0, "ElapsedMin": 0.0}
PRESS_TAGS = {"ForceKN": 13.0, "PrecompKN": 2.0, "TabletWeightMg": 650.0, "PunchDiameterMm": 12.0, "TurretRPM": 30.0}
# Modbus holding registers for PRESS1 (float32, big-endian words): 0 ForceKN, 2 PrecompKN, 4 TabletWeightMg,
# 6 PunchDiameterMm, 8 TurretRPM; 20..27 batch number as ASCII (16 characters)
MODBUS_MAP = {"ForceKN": 0, "PrecompKN": 2, "TabletWeightMg": 4, "PunchDiameterMm": 6, "TurretRPM": 8}
MODBUS_BATCH = 20


class Plant:
    def __init__(self, fault: str, every: int, seed: int):
        self.rng = random.Random(seed)
        self.fault, self.every = fault, every
        self.n = 1
        self.prefix = time.strftime("B%d%H%M-")  # batch numbers stay unique across restarts: B220024-001, B220024-002…
        self.fbd_t = 0.0
        self.press_batch = ""
        self.press_t = 0.0
        self._new_fbd_batch()

    def _faulty(self, n: int) -> bool:
        return self.fault != "none" and self.every > 0 and n % self.every == 0

    def _new_fbd_batch(self) -> None:
        f = self._faulty(self.n)
        self.fbd_batch = f"{self.prefix}{self.n:03d}"
        self.fbd_target = (39.0 if f and self.fault == "short-dry" else self.rng.gauss(60, 1.5))
        self.fbd_rh = 25.0 if f and self.fault == "humid-air" else self.rng.gauss(8, 0.8)
        self.fbd_final = 1.6 + 0.09 * max(0.0, 60 - self.fbd_target) + 0.06 * max(0.0, self.fbd_rh - 8) + self.rng.gauss(0, 0.12)
        self.fbd_t = 0.0

    def step(self, sim_min: float) -> tuple[dict[str, float], dict[str, float]]:
        r = self.rng
        self.fbd_t += sim_min
        if self.fbd_t >= self.fbd_target:  # drying done: this batch goes to the press, the next one starts drying
            self.press_batch, self.press_t = self.fbd_batch, 0.0
            self.press_force = 18.5 if self._faulty(self.n) and self.fault == "over-compress" else 13.0
            self.n += 1
            self._new_fbd_batch()
        t, T = self.fbd_t, self.fbd_target
        fbd = {"InletTemp": r.gauss(60, 0.6), "OutletTemp": 30 + 0.25 * t + r.gauss(0, 0.4), "ProductTemp": 28 + 0.27 * t + r.gauss(0, 0.4),
               "InletRH": self.fbd_rh + r.gauss(0, 0.5), "AirFlow": r.gauss(3000, 25),
               "LOD": self.fbd_final + max(0.0, 1 - t / T) * 18 + r.gauss(0, 0.05), "ElapsedMin": round(t, 2)}
        self.press_t += sim_min
        press = {"ForceKN": (self.press_force if self.press_batch else 0.0) + r.gauss(0, 0.35), "PrecompKN": r.gauss(2.0, 0.12),
                 "TabletWeightMg": r.gauss(650, 6.5), "PunchDiameterMm": 12.0, "TurretRPM": 30.0}
        return fbd, press


async def main(a: argparse.Namespace) -> None:
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://0.0.0.0:{a.port}/eurveda-sim/")
    server.set_server_name("Eurveda plant simulator")
    idx = await server.register_namespace("urn:eurveda:sim")
    objs = server.nodes.objects
    nodes: dict[str, dict[str, object]] = {"FBD1": {}, "PRESS1": {}}
    for machine, tags in (("FBD1", FBD_TAGS), ("PRESS1", PRESS_TAGS)):
        obj = await objs.add_object(ua.NodeId(machine, idx), ua.QualifiedName(machine, idx))
        for tag, v in tags.items():
            nodes[machine][tag] = await obj.add_variable(ua.NodeId(f"{machine}.{tag}", idx), ua.QualifiedName(tag, idx), float(v))
        nodes[machine]["BatchNo"] = await obj.add_variable(ua.NodeId(f"{machine}.BatchNo", idx), ua.QualifiedName("BatchNo", idx), "")

    regs = await start_modbus(a.modbus) if a.modbus else None
    plant = Plant(a.fault, a.fault_every, a.seed)
    tick = 1.0
    async with server:
        log.info("OPC UA on opc.tcp://localhost:%d/eurveda-sim/ (namespace %d)%s; %gx speed, fault=%s every %d",
                 a.port, idx, f", Modbus on :{a.modbus}" if a.modbus else "", a.speed, a.fault, a.fault_every)
        while True:
            fbd, press = plant.step(tick * a.speed / 60.0)
            for k, v in fbd.items():
                await nodes["FBD1"][k].write_value(float(v))
            await nodes["FBD1"]["BatchNo"].write_value(plant.fbd_batch)
            for k, v in press.items():
                await nodes["PRESS1"][k].write_value(float(v))
            await nodes["PRESS1"]["BatchNo"].write_value(plant.press_batch)
            if regs is not None:
                for k, at in MODBUS_MAP.items():
                    hi, lo = struct.unpack(">HH", struct.pack(">f", press[k]))
                    regs.setValues(3, at, [hi, lo])
                b = plant.press_batch.encode("ascii").ljust(16, b"\x00")[:16]
                regs.setValues(3, MODBUS_BATCH, list(struct.unpack(">8H", b)))
            await asyncio.sleep(tick)


class Registers:
    """Holding registers of a minimal Modbus TCP server (function 3, read holding registers — all the agent uses)."""

    def __init__(self, n: int = 64):
        self.r = [0] * n

    def setValues(self, _fc: int, at: int, values: list[int]) -> None:  # noqa: N802 — same call shape as pymodbus
        self.r[at:at + len(values)] = values


async def start_modbus(port: int) -> Registers:
    """Serve PRESS1 over Modbus TCP: MBAP header + PDU, function 3 only (others answer 'illegal function')."""
    regs = Registers()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                head = await reader.readexactly(7)
                tid, _proto, length, unit = struct.unpack(">HHHB", head)
                pdu = await reader.readexactly(length - 1)
                fc = pdu[0]
                if fc == 3 and len(pdu) >= 5:
                    at, count = struct.unpack(">HH", pdu[1:5])
                    if at + count > len(regs.r) or count == 0:
                        body = struct.pack(">BB", fc | 0x80, 2)  # illegal data address
                    else:
                        body = struct.pack(">BB", fc, 2 * count) + struct.pack(f">{count}H", *regs.r[at:at + count])
                else:
                    body = struct.pack(">BB", fc | 0x80, 1)  # illegal function
                writer.write(struct.pack(">HHHB", tid, 0, len(body) + 1, unit) + body)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()

    await asyncio.start_server(handle, "0.0.0.0", port)
    return regs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4840)
    ap.add_argument("--modbus", type=int, default=0, help="also serve PRESS1 over Modbus TCP on this port")
    ap.add_argument("--speed", type=float, default=30.0, help="simulated seconds per real second")
    ap.add_argument("--fault", choices=["none", "short-dry", "over-compress", "humid-air"], default="short-dry")
    ap.add_argument("--fault-every", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    asyncio.run(main(ap.parse_args()))
