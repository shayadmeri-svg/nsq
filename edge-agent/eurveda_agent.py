"""Eurveda edge agent: reads plant machines over OPC UA or Modbus TCP, read-only, and streams the readings to
Eurveda's Plant data (POST /api/ingest/plant-data), where they join the batch records and the failure tree.

    python eurveda_agent.py --config config.yaml              run (poll machines, buffer, push)
    python eurveda_agent.py --config config.yaml --check      read every configured tag once and print it (commissioning)
    python eurveda_agent.py --browse opc.tcp://10.0.0.20:4840 list a machine's OPC UA tags (to fill in the config)
    python eurveda_agent.py --config config.yaml --dry-run    poll and print readings without sending

It never writes to a machine. Readings are kept in a local SQLite queue until Eurveda accepts them, so a network
outage loses nothing (up to `buffer_max_rows`, oldest dropped first).

A reading = one machine at one moment: {machine, format, ts, batch_no, product, values: {field: number}}. `format`
and the field names are Eurveda's (Plant data → Formats), e.g. a fluid-bed dryer is `fbd` with inlet_c, outlet_c,
product_c, inlet_rh_pct, air_m3_h, lod_pct, elapsed_min. The batch number comes from a machine tag, a file the
operator updates, an environment variable, or a fixed value; readings without a batch number are skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sqlite3
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

__version__ = "0.1.0"
log = logging.getLogger("eurveda-agent")
STOP = threading.Event()


# --- sources ------------------------------------------------------------------------------------------------------

class Source:
    """One machine. read() → (values, batch_no, product); raises on a connection problem (the caller reconnects)."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.name = cfg["name"]

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read(self) -> tuple[dict[str, float], str, str]:
        raise NotImplementedError

    def _meta(self, spec: Optional[dict[str, Any]], reader) -> str:
        """Batch number / product from {fixed}, {env}, {file} or a machine tag (read by `reader`)."""
        if not spec:
            return ""
        if "fixed" in spec:
            return str(spec["fixed"])
        if "env" in spec:
            return os.environ.get(spec["env"], "")
        if "file" in spec:
            p = Path(spec["file"])
            return p.read_text(encoding="utf-8").strip() if p.exists() else ""
        v = reader(spec)
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("ascii", errors="ignore")
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v if v is not None else "").strip().strip("\x00")


class OpcUaSource(Source):
    """OPC UA (asyncua, synchronous wrapper). Tags are NodeIds, e.g. "ns=2;s=FBD1.InletTemp"."""

    def connect(self) -> None:
        from asyncua.sync import Client

        self.client = Client(self.cfg["endpoint"], timeout=float(self.cfg.get("timeout_s", 8)))
        sec = self.cfg.get("security")  # e.g. "Basic256Sha256,SignAndEncrypt,agent-cert.der,agent-key.pem"
        if sec:
            self.client.set_security_string(sec)
        if self.cfg.get("username"):
            self.client.set_user(self.cfg["username"])
            self.client.set_password(os.environ.get(self.cfg.get("password_env", ""), ""))
        self.client.connect()
        self.nodes = {f: self.client.get_node(n) for f, n in self.cfg["tags"].items()}

    def close(self) -> None:
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _node_value(self, spec: dict[str, Any]) -> Any:
        return self.client.get_node(spec["node"]).read_value()

    def read(self) -> tuple[dict[str, float], str, str]:
        vals = {}
        for f, node in self.nodes.items():
            v = node.read_value()
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals[f] = float(v) * float(self.cfg.get("scale", {}).get(f, 1))
        return vals, self._meta(self.cfg.get("batch"), self._node_value), self._meta(self.cfg.get("product"), self._node_value)


class ModbusSource(Source):
    """Modbus TCP (pymodbus). Tags: {register, type: float32|int16|uint16|int32|uint32, scale, function: holding|input,
    word_order: big|little}. Batch numbers stored as ASCII in registers: {register, type: string, length: n}."""

    SIZES = {"float32": 2, "int32": 2, "uint32": 2, "int16": 1, "uint16": 1}

    def connect(self) -> None:
        from pymodbus.client import ModbusTcpClient

        self.client = ModbusTcpClient(self.cfg["host"], port=int(self.cfg.get("port", 502)), timeout=float(self.cfg.get("timeout_s", 5)))
        if not self.client.connect():
            raise ConnectionError(f"Modbus {self.cfg['host']}:{self.cfg.get('port', 502)} unreachable")

    def close(self) -> None:
        self.client.close()

    def _regs(self, spec: dict[str, Any], count: int) -> list[int]:
        fn = self.client.read_input_registers if spec.get("function") == "input" else self.client.read_holding_registers
        unit = int(self.cfg.get("unit", 1))
        try:
            rr = fn(int(spec["register"]), count=count, device_id=unit)  # pymodbus ≥ 3.10
        except TypeError:
            rr = fn(int(spec["register"]), count=count, slave=unit)  # older pymodbus
        if rr.isError():
            raise IOError(f"Modbus read {spec['register']}: {rr}")
        return list(rr.registers)

    def _decode(self, spec: dict[str, Any]) -> Any:
        t = spec.get("type", "float32")
        if t == "string":
            regs = self._regs(spec, int(spec.get("length", 8)))
            return b"".join(struct.pack(">H", r) for r in regs)
        regs = self._regs(spec, self.SIZES[t])
        if spec.get("word_order", "big") == "little" and len(regs) == 2:
            regs = regs[::-1]
        raw = b"".join(struct.pack(">H", r) for r in regs)
        v = {"float32": ">f", "int32": ">i", "uint32": ">I", "int16": ">h", "uint16": ">H"}[t]
        return struct.unpack(v, raw)[0] * float(spec.get("scale", 1))

    def read(self) -> tuple[dict[str, float], str, str]:
        vals = {f: float(self._decode(spec)) for f, spec in self.cfg["tags"].items()}
        return vals, self._meta(self.cfg.get("batch"), self._decode), self._meta(self.cfg.get("product"), self._decode)


def make_source(cfg: dict[str, Any]) -> Source:
    proto = cfg.get("protocol", "opcua")
    if proto == "opcua":
        return OpcUaSource(cfg)
    if proto == "modbus":
        return ModbusSource(cfg)
    raise ValueError(f"{cfg['name']}: unknown protocol {proto!r} (opcua | modbus)")


# --- buffer -------------------------------------------------------------------------------------------------------

class Buffer:
    """SQLite queue: readings wait here until Eurveda accepts them."""

    def __init__(self, path: str, max_rows: int):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("create table if not exists q (id integer primary key autoincrement, body text not null)")
        self.lock = threading.Lock()
        self.max_rows = max_rows

    def put(self, reading: dict[str, Any]) -> None:
        with self.lock:
            self.db.execute("insert into q (body) values (?)", (json.dumps(reading),))
            n = self.db.execute("select count(*) from q").fetchone()[0]
            if n > self.max_rows:
                self.db.execute("delete from q where id in (select id from q order by id limit ?)", (n - self.max_rows,))
                log.warning("buffer full: dropped %d oldest readings", n - self.max_rows)
            self.db.commit()

    def take(self, n: int) -> list[tuple[int, dict[str, Any]]]:
        with self.lock:
            return [(i, json.loads(b)) for i, b in self.db.execute("select id, body from q order by id limit ?", (n,)).fetchall()]

    def drop(self, last_id: int) -> None:
        with self.lock:
            self.db.execute("delete from q where id <= ?", (last_id,))
            self.db.commit()

    def size(self) -> int:
        with self.lock:
            return self.db.execute("select count(*) from q").fetchone()[0]


# --- loops --------------------------------------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def poll(cfg: dict[str, Any], buf: Optional[Buffer], dry: bool = False) -> None:
    src = make_source(cfg)
    every = float(cfg.get("poll_s", 5))
    backoff = 2.0
    while not STOP.is_set():
        try:
            src.connect()
            log.info("%s: connected (%s)", src.name, cfg.get("endpoint") or cfg.get("host"))
            backoff = 2.0
            while not STOP.is_set():
                t0 = time.monotonic()
                vals, batch, product = src.read()
                if batch or not cfg.get("skip_without_batch", True):
                    r = {"machine": src.name, "format": cfg["format"], "ts": now_iso(), "batch_no": batch, "product": product, "values": vals}
                    if dry:
                        print(json.dumps(r))
                    else:
                        buf.put(r)
                STOP.wait(max(0.0, every - (time.monotonic() - t0)))
        except Exception as exc:  # noqa: BLE001 — any machine/network failure: log, reconnect with backoff
            log.warning("%s: %s — retrying in %.0f s", src.name, exc, backoff)
            src.close()
            STOP.wait(backoff)
            backoff = min(backoff * 2, 60.0)
    src.close()


def push(conf: dict[str, Any], buf: Buffer) -> None:
    url = conf["url"].rstrip("/") + "/api/ingest/plant-data"
    token = conf.get("token") or os.environ.get(conf.get("token_env", "EURVEDA_TOKEN"), "")
    if not token:
        log.error("no connector token: set eurveda.token_env (default EURVEDA_TOKEN)")
        STOP.set()
        return
    every = float(conf.get("push_every_s", 15))
    agent = {"version": __version__, "host": socket.gethostname()}
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "x-nsq-client": "edge-agent", "Content-Type": "application/json"})
    backoff = every
    while not STOP.wait(every if backoff == every else backoff):
        while True:
            rows = buf.take(2000)
            try:
                r = s.post(url, data=json.dumps({"agent": agent, "readings": [b for _, b in rows]}), timeout=30,
                           verify=conf.get("verify_tls", True))
            except requests.RequestException as exc:
                log.warning("push failed: %s (%d buffered)", exc, buf.size())
                backoff = min(backoff * 2, 300.0)
                break
            if r.status_code == 401:
                log.error("Eurveda rejected the token (revoked?): stopping")
                STOP.set()
                return
            if r.status_code >= 400:
                log.warning("push: HTTP %d %s (%d buffered)", r.status_code, r.text[:200], buf.size())
                backoff = min(backoff * 2, 300.0)
                break
            backoff = every
            if rows:
                buf.drop(rows[-1][0])
                log.info("pushed %d readings (%s)", len(rows), r.json())
            if len(rows) < 2000:
                break


def check(cfg_all: dict[str, Any]) -> int:
    """Read every configured machine once and print what Eurveda would receive."""
    bad = 0
    for m in cfg_all["machines"]:
        src = make_source(m)
        try:
            src.connect()
            vals, batch, product = src.read()
            print(f"\n{m['name']} ({m['format']}, {m.get('protocol', 'opcua')}): batch={batch!r} product={product!r}")
            for k, v in vals.items():
                print(f"   {k:<22} {v}")
        except Exception as exc:  # noqa: BLE001
            bad += 1
            print(f"\n{m['name']}: FAILED — {exc}")
        finally:
            src.close()
    return 1 if bad else 0


def browse(endpoint: str, depth: int = 4) -> None:
    """Print the OPC UA address space under Objects: NodeId, browse name, current value."""
    from asyncua.sync import Client

    with Client(endpoint, timeout=8) as c:
        def walk(node, d):
            for ch in node.get_children():
                try:
                    name = ch.read_browse_name().Name
                    try:
                        val = ch.read_value()
                        print(f"{'  ' * d}{ch.nodeid.to_string():<40} {name:<28} = {val!r}")
                    except Exception:  # noqa: BLE001 — folders/objects have no value
                        print(f"{'  ' * d}{ch.nodeid.to_string():<40} {name}/")
                    if d < depth:
                        walk(ch, d + 1)
                except Exception:  # noqa: BLE001
                    continue
        walk(c.nodes.objects, 0)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="YAML config (see config.example.yaml)")
    ap.add_argument("--check", action="store_true", help="read each machine once and print, then exit")
    ap.add_argument("--dry-run", action="store_true", help="poll and print readings, send nothing")
    ap.add_argument("--browse", metavar="OPC_UA_ENDPOINT", help="list a machine's OPC UA tags and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("asyncua", "pymodbus", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if a.browse:
        browse(a.browse)
        return 0
    if not a.config:
        ap.error("--config is required")
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    if a.check:
        return check(cfg)
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    conf = cfg["eurveda"]
    buf = None if a.dry_run else Buffer(conf.get("buffer", "eurveda-buffer.sqlite"), int(conf.get("buffer_max_rows", 500_000)))
    threads = [threading.Thread(target=poll, args=(m, buf, a.dry_run), daemon=True, name=m["name"]) for m in cfg["machines"]]
    if buf is not None:
        threads.append(threading.Thread(target=push, args=(conf, buf), daemon=True, name="push"))
    for t in threads:
        t.start()
    log.info("eurveda-agent %s: %d machine(s)%s", __version__, len(cfg["machines"]), " (dry run)" if a.dry_run else "")
    while not STOP.is_set():
        STOP.wait(1)
    for t in threads:
        t.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
