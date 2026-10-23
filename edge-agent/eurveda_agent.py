"""Eurveda edge agent: reads plant machines and systems, read-only, and streams the readings to Eurveda (Plant data and
Connect), where they join the batch records and the failure tree.

Protocols (`protocol:` per machine; each library is imported only when a machine uses it):
    opcua         OPC UA (asyncua)                          tags: ns=2;s=FBD1.InletTemp
    modbus        Modbus TCP (pymodbus)                     tags: 40001:float32 · hr100:int16*0.1 · ir5:uint16 · {register: …}
    modbus_rtu    Modbus RTU over RS-485 (pymodbus)         same tags; serial_port, baudrate, parity, unit
    s7            Siemens S7 (python-snap7, ISO-on-TCP)     tags: DB1.DBD0:REAL · DB10.DBW4:INT · DB1.DBX2.1:BOOL · MD100:REAL
    ethernet_ip   Rockwell Logix (pycomm3, CIP)             tags: Dryer_InletTemp · Program:Main.LOD
    mqtt          MQTT broker (paho-mqtt)                   tags: plant/fbd1/inlet_temp · plant/fbd1/state|inlet.temp
    rest          HTTP JSON, or AVEVA PI Web API (mode: pi) tags: data.inlet_temp · values[0].v · a PI WebId
    sql           SQL historian (SQLAlchemy)                tags: the tag name, passed to `query` as :tag
    serial_ascii  RS-232 balances (pyserial)                tags: the command, e.g. SI (Mettler MT-SICS), ESC P (Sartorius)

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
import re
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

__version__ = "0.2.0"
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
        self.nodes = {f: self._node(f, n) for f, n in self.cfg["tags"].items()}

    def _node(self, field: str, node_id: str) -> Any:
        try:
            return self.client.get_node(str(node_id).strip())
        except Exception as exc:  # asyncua's own message names the string, not the field
            raise ValueError(f"{field}: {node_id!r} is not an OPC UA node id (they look like ns=2;s=FBD1.InletTemp)") from exc

    def close(self) -> None:
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _node_value(self, spec: dict[str, Any]) -> Any:
        return self._node("tag", spec.get("node") or spec.get("tag")).read_value()

    def read(self) -> tuple[dict[str, float], str, str]:
        vals = {}
        for f, node in self.nodes.items():
            v = node.read_value()
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals[f] = float(v) * float(self.cfg.get("scale", {}).get(f, 1))
        return vals, self._meta(self.cfg.get("batch"), self._node_value), self._meta(self.cfg.get("product"), self._node_value)


def parse_modbus(tag: Any) -> dict[str, Any]:
    """A Modbus address as written in a manual or the setup wizard → {register, function, type, word_order, scale, length}.
    40001 / 400001 → holding register 0 (1-based 4xxxx), 30001 → input register 0, hr100 / ir100 → register 100 as is,
    a bare number below 30001 → holding register as is; then :float32|int16|uint16|int32|uint32|stringN, :big|little,
    *scale. A dict is taken as it is (the config file's long form)."""
    if isinstance(tag, dict):
        return tag
    m = re.fullmatch(r"(?i)(hr|ir)?(\d+)(?::(float32|int32|uint32|int16|uint16|string(\d+)))?(?::(big|little))?(?:\*(-?[\d.]+))?", str(tag).strip())
    if not m:
        raise ValueError(f"{tag!r} is not a Modbus address (e.g. 40001:float32, hr100:int16*0.1)")
    pre, num, typ, slen, order, scale = m.groups()
    n, fn = int(num), "holding"
    if pre:
        fn = "input" if pre.lower() == "ir" else "holding"
    elif 300001 <= n <= 465536:
        fn, n = ("input", n - 300001) if n < 400001 else ("holding", n - 400001)
    elif 30001 <= n <= 49999:
        fn, n = ("input", n - 30001) if n < 40001 else ("holding", n - 40001)
    spec = {"register": n, "function": fn, "type": "string" if slen else (typ or "float32").lower(), "word_order": (order or "big").lower(),
            "scale": float(scale) if scale else 1.0}
    if slen:
        spec["length"] = (int(slen) + 1) // 2
    return spec


class ModbusSource(Source):
    """Modbus TCP or RTU (pymodbus). Tags: an address string (parse_modbus) or {register, type: float32|int16|uint16|
    int32|uint32|string, scale, function: holding|input, word_order: big|little, length}."""

    SIZES = {"float32": 2, "int32": 2, "uint32": 2, "int16": 1, "uint16": 1}

    def connect(self) -> None:
        if self.cfg.get("protocol") == "modbus_rtu":
            from pymodbus.client import ModbusSerialClient

            self.client = ModbusSerialClient(port=self.cfg["serial_port"], baudrate=int(self.cfg.get("baudrate", 9600)),
                                             parity=str(self.cfg.get("parity", "N"))[:1].upper(), stopbits=int(self.cfg.get("stopbits", 1)),
                                             bytesize=8, timeout=float(self.cfg.get("timeout_s", 3)))
            where = self.cfg["serial_port"]
        else:
            from pymodbus.client import ModbusTcpClient

            self.client = ModbusTcpClient(self.cfg["host"], port=int(self.cfg.get("port", 502)), timeout=float(self.cfg.get("timeout_s", 5)))
            where = f"{self.cfg['host']}:{self.cfg.get('port', 502)}"
        if not self.client.connect():
            raise ConnectionError(f"Modbus {where} unreachable")

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass

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

    def _decode(self, spec: Any) -> Any:
        spec = parse_modbus(spec.get("tag", spec) if isinstance(spec, dict) and "tag" in spec else spec)
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


class S7Source(Source):
    """Siemens S7-300/400/1200/1500 over ISO-on-TCP (python-snap7). Tags: DB1.DBD0:REAL, DB10.DBW4:INT, DB1.DBX2.1:BOOL,
    MD100:REAL, IW64:INT, DB2.DBB0:STRING20, optionally *scale. Without a type: D → REAL, W → INT, B → BYTE, X → BOOL."""

    SIZE = {"REAL": 4, "LREAL": 8, "INT": 2, "DINT": 4, "WORD": 2, "DWORD": 4, "BYTE": 1, "BOOL": 1}
    FMT = {"REAL": ">f", "LREAL": ">d", "INT": ">h", "DINT": ">i", "WORD": ">H", "DWORD": ">I", "BYTE": ">B"}
    DEFAULT = {"D": "REAL", "W": "INT", "B": "BYTE", "X": "BOOL", "": "BYTE"}

    @staticmethod
    def parse(tag: str) -> dict[str, Any]:
        m = re.fullmatch(r"(?i)(?:DB(\d+)\.DB([BWDX])(\d+)(?:\.(\d))?|([MIQE])([BWDX]?)(\d+)(?:\.(\d))?)(?::([A-Z]+)(\d*))?(?:\*(-?[\d.]+))?",
                         str(tag).strip())
        if not m:
            raise ValueError(f"{tag!r} is not an S7 address (e.g. DB1.DBD0:REAL, MD100:REAL, DB1.DBX2.1:BOOL)")
        db, w1, off1, bit1, area, w2, off2, bit2, typ, slen, scale = m.groups()
        width = (w1 or w2 or "").upper()
        t = (typ or S7Source.DEFAULT[width]).upper()
        return {"area": "DB" if db else {"E": "I"}.get(area.upper(), area.upper()), "db": int(db or 0), "start": int(off1 or off2),
                "bit": int(bit1 or bit2 or 0), "type": t, "strlen": int(slen) if t == "STRING" and slen else 254,
                "scale": float(scale) if scale else 1.0}

    def connect(self) -> None:
        import snap7

        self.client = snap7.client.Client()
        self.client.connect(self.cfg["host"], int(self.cfg.get("rack", 0)), int(self.cfg.get("slot", 1)), int(self.cfg.get("port", 102)))
        self.specs = {f: self.parse(t) for f, t in self.cfg["tags"].items()}

    def close(self) -> None:
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _read(self, sp: dict[str, Any]) -> Any:
        from snap7.type import Area

        size = sp["strlen"] + 2 if sp["type"] == "STRING" else self.SIZE[sp["type"]]
        if sp["area"] == "DB":
            raw = bytes(self.client.db_read(sp["db"], sp["start"], size))
        else:
            raw = bytes(self.client.read_area({"M": Area.MK, "I": Area.PE, "Q": Area.PA}[sp["area"]], 0, sp["start"], size))
        if sp["type"] == "BOOL":
            return float((raw[0] >> sp["bit"]) & 1)
        if sp["type"] == "STRING":  # S7 string: max length, actual length, characters
            return raw[2:2 + raw[1]].decode("latin-1")
        return struct.unpack(self.FMT[sp["type"]], raw)[0] * sp["scale"]

    def _meta_read(self, spec: dict[str, Any]) -> Any:
        return self._read(self.parse(spec.get("tag") or spec.get("node")))

    def read(self) -> tuple[dict[str, float], str, str]:
        vals = {f: float(self._read(sp)) for f, sp in self.specs.items()}
        return vals, self._meta(self.cfg.get("batch"), self._meta_read), self._meta(self.cfg.get("product"), self._meta_read)


class EtherNetIPSource(Source):
    """Allen-Bradley ControlLogix / CompactLogix over EtherNet/IP (pycomm3 LogixDriver). Tags are Logix tag names."""

    def connect(self) -> None:
        from pycomm3 import LogixDriver

        self.plc = LogixDriver(self.cfg["host"])
        self.plc.open()

    def close(self) -> None:
        try:
            self.plc.close()
        except Exception:  # noqa: BLE001
            pass

    def _one(self, spec: dict[str, Any]) -> Any:
        r = self.plc.read(spec.get("tag") or spec.get("node"))
        if r.error:
            raise IOError(f"{r.tag}: {r.error}")
        return r.value

    def read(self) -> tuple[dict[str, float], str, str]:
        fields, names = list(self.cfg["tags"]), list(self.cfg["tags"].values())
        res = self.plc.read(*names)
        res = res if isinstance(res, list) else [res]
        vals = {}
        for f, r in zip(fields, res):
            if r.error:
                raise IOError(f"{f} ({r.tag}): {r.error}")
            if isinstance(r.value, (int, float)) and not isinstance(r.value, bool):
                vals[f] = float(r.value)
            elif isinstance(r.value, bool):
                vals[f] = float(r.value)
        return vals, self._meta(self.cfg.get("batch"), self._one), self._meta(self.cfg.get("product"), self._one)


def json_path(doc: Any, path: str) -> Any:
    """data.items[0].value → doc["data"]["items"][0]["value"]; None when any step is missing."""
    cur = doc
    for key, idx in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path):
        try:
            cur = cur[int(idx)] if idx else cur[key]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict) and "Value" in v:  # PI digital states and some gateways: {"Name": …, "Value": n}
        return _number(v["Value"])
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


class MqttSource(Source):
    """MQTT (paho-mqtt): subscribes to each tag's topic and keeps the last message. A tag is a topic whose payload is a
    number, or topic|json.path for JSON payloads. Retained messages give a value at once; otherwise read() returns
    what has arrived (and a test read waits up to `timeout_s` for every topic)."""

    def connect(self) -> None:
        from urllib.parse import urlparse

        import paho.mqtt.client as mqtt

        u = urlparse(self.cfg["broker"] if "://" in self.cfg["broker"] else "mqtt://" + self.cfg["broker"])
        self.last: dict[str, Any] = {}
        self.got = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"eurveda-{socket.gethostname()}-{self.name}"[:60])
        if self.cfg.get("username"):
            self.client.username_pw_set(self.cfg["username"], os.environ.get(self.cfg.get("password_env", ""), None))
        if u.scheme in ("mqtts", "ssl", "tls"):
            self.client.tls_set()
        self.topics = {f: str(t).split("|", 1) for f, t in self.cfg["tags"].items()}
        extra = [str(s.get("tag")).split("|", 1) for s in (self.cfg.get("batch"), self.cfg.get("product")) if isinstance(s, dict) and s.get("tag")]

        def on_message(_c, _u, msg):
            self.last[msg.topic] = msg.payload
            self.got.set()

        def on_connect(c, _u, _f, rc, _p=None):
            for topic in {t[0] for t in [*self.topics.values(), *extra]}:
                c.subscribe(topic, qos=0)

        self.client.on_message, self.client.on_connect = on_message, on_connect
        self.client.connect(u.hostname, u.port or (8883 if u.scheme in ("mqtts", "ssl", "tls") else 1883), keepalive=30)
        self.client.loop_start()
        deadline = time.monotonic() + float(self.cfg.get("timeout_s", 5))
        while time.monotonic() < deadline and len({t[0] for t in self.topics.values()} - set(self.last)) > 0:
            time.sleep(0.1)

    def close(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _value(self, topic_path: list[str]) -> Any:
        raw = self.last.get(topic_path[0])
        if raw is None:
            return None
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        if len(topic_path) == 1:
            return text
        try:
            return json_path(json.loads(text), topic_path[1])
        except ValueError:
            return None

    def read(self) -> tuple[dict[str, float], str, str]:
        vals = {f: n for f, tp in self.topics.items() if (n := _number(self._value(tp))) is not None}
        if not vals:
            raise IOError("no message yet on the configured topics")
        meta = lambda spec: self._value(str(spec.get("tag")).split("|", 1))  # noqa: E731
        return vals, self._meta(self.cfg.get("batch"), meta), self._meta(self.cfg.get("product"), meta)


class RestSource(Source):
    """HTTP JSON polled by the agent. mode json (default): one GET of `url`, each tag a path into the response.
    mode pi: AVEVA PI Web API at `url` (…/piwebapi); each tag is a point's WebId, read from /streams/{webid}/value.
    auth_env names an environment variable holding user:password (basic) or a bearer token."""

    def connect(self) -> None:
        self.s = requests.Session()
        auth = os.environ.get(self.cfg.get("auth_env", ""), "") if self.cfg.get("auth_env") else ""
        if ":" in auth:
            self.s.auth = tuple(auth.split(":", 1))
        elif auth:
            self.s.headers["Authorization"] = f"Bearer {auth}"
        self.s.headers["Accept"] = "application/json"
        self.verify = str(self.cfg.get("verify_tls", "true")).lower() not in ("false", "0", "no")
        self.timeout = float(self.cfg.get("timeout_s", 10))

    def _get(self, url: str) -> Any:
        r = self.s.get(url, timeout=self.timeout, verify=self.verify)
        r.raise_for_status()
        return r.json()

    def read(self) -> tuple[dict[str, float], str, str]:
        base = self.cfg["url"].rstrip("/")
        if str(self.cfg.get("mode", "json")).lower() == "pi":
            one = lambda tag: self._get(f"{base}/streams/{tag}/value").get("Value")  # noqa: E731
        else:
            doc = self._get(base)
            one = lambda tag: json_path(doc, tag)  # noqa: E731
        vals = {f: n for f, t in self.cfg["tags"].items() if (n := _number(one(t))) is not None}
        meta = lambda spec: one(spec.get("tag") or spec.get("node"))  # noqa: E731
        return vals, self._meta(self.cfg.get("batch"), meta), self._meta(self.cfg.get("product"), meta)


class SqlSource(Source):
    """A historian kept in SQL (SQLAlchemy URL from the environment variable `dsn_env`, e.g.
    mssql+pymssql://user:pass@host/Runtime). `query` returns a tag's latest value in its first column, :tag bound."""

    DEFAULT_QUERY = "SELECT value FROM readings WHERE tag = :tag ORDER BY ts DESC LIMIT 1"

    def connect(self) -> None:
        from sqlalchemy import create_engine, text

        dsn = os.environ.get(self.cfg.get("dsn_env", ""), "") or self.cfg.get("dsn", "")
        if not dsn:
            raise ValueError(f"set the connection URL in the environment variable {self.cfg.get('dsn_env')!r} on the agent's PC")
        self.engine = create_engine(dsn, pool_pre_ping=True)
        self.q = text(self.cfg.get("query") or self.DEFAULT_QUERY)

    def close(self) -> None:
        try:
            self.engine.dispose()
        except Exception:  # noqa: BLE001
            pass

    def _one(self, conn, tag: str) -> Any:
        row = conn.execute(self.q, {"tag": tag}).first()
        return row[0] if row else None

    def read(self) -> tuple[dict[str, float], str, str]:
        with self.engine.connect() as conn:
            vals = {f: n for f, t in self.cfg["tags"].items() if (n := _number(self._one(conn, t))) is not None}
            meta = lambda spec: self._one(conn, spec.get("tag") or spec.get("node"))  # noqa: E731
            return vals, self._meta(self.cfg.get("batch"), meta), self._meta(self.cfg.get("product"), meta)


class SerialAsciiSource(Source):
    """Balances and instruments that answer a text command on RS-232 (pyserial): each tag is the command (SI for
    Mettler-Toledo MT-SICS, "ESC P" for Sartorius); the first number in the reply is the value, in the unit it shows."""

    def connect(self) -> None:
        import serial

        self.port = serial.Serial(self.cfg["serial_port"], baudrate=int(self.cfg.get("baudrate", 9600)), timeout=float(self.cfg.get("timeout_s", 2)))

    def close(self) -> None:
        try:
            self.port.close()
        except Exception:  # noqa: BLE001
            pass

    def _ask(self, cmd: str) -> Optional[float]:
        raw = cmd.replace("ESC ", "\x1b").replace("ESC", "\x1b")
        self.port.reset_input_buffer()
        self.port.write((raw + str(self.cfg.get("eol", "\r\n")).encode().decode("unicode_escape")).encode("ascii"))
        reply = self.port.readline().decode("ascii", errors="replace")
        m = re.search(r"[-+]?\s*\d+(?:\.\d+)?", reply)
        if not m:
            raise IOError(f"{cmd!r}: no number in the reply {reply.strip()!r}")
        return float(m.group(0).replace(" ", ""))

    def read(self) -> tuple[dict[str, float], str, str]:
        vals = {f: self._ask(str(c)) for f, c in self.cfg["tags"].items()}
        return vals, self._meta(self.cfg.get("batch"), lambda s: s.get("tag")), self._meta(self.cfg.get("product"), lambda s: s.get("tag"))


SOURCES = {"opcua": OpcUaSource, "modbus": ModbusSource, "modbus_tcp": ModbusSource, "modbus_rtu": ModbusSource, "s7": S7Source,
           "ethernet_ip": EtherNetIPSource, "mqtt": MqttSource, "rest": RestSource, "sql": SqlSource, "serial_ascii": SerialAsciiSource}


def make_source(cfg: dict[str, Any]) -> Source:
    proto = cfg.get("protocol", "opcua")
    if proto not in SOURCES:
        raise ValueError(f"{cfg['name']}: unknown protocol {proto!r} ({' | '.join(SOURCES)})")
    need = {"opcua": "endpoint", "modbus": "host", "modbus_tcp": "host", "s7": "host", "ethernet_ip": "host", "mqtt": "broker", "rest": "url",
            "modbus_rtu": "serial_port", "serial_ascii": "serial_port"}.get(proto)
    if need and not cfg.get(need):
        raise ValueError(f"{cfg['name']}: no {need} set for this machine (Plant setup → Connections)")
    return SOURCES[proto](cfg)


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


def poll(cfg: dict[str, Any], buf: Optional[Buffer], dry: bool = False, stop: Optional[threading.Event] = None) -> None:
    src = make_source(cfg)
    every = float(cfg.get("poll_s", 5))
    backoff = 2.0
    halt = stop or STOP
    while not STOP.is_set() and not halt.is_set():
        try:
            src.connect()
            log.info("%s: connected (%s)", src.name, cfg.get("endpoint") or cfg.get("host") or cfg.get("broker") or cfg.get("url") or cfg.get("serial_port") or cfg.get("protocol"))
            backoff = 2.0
            while not STOP.is_set() and not halt.is_set():
                t0 = time.monotonic()
                vals, batch, product = src.read()
                if batch or not cfg.get("skip_without_batch", True):
                    r = {"machine": src.name, "format": cfg["format"], "ts": now_iso(), "batch_no": batch, "product": product, "values": vals}
                    if dry:
                        print(json.dumps(r))
                    else:
                        buf.put(r)
                halt.wait(max(0.0, every - (time.monotonic() - t0)))
        except Exception as exc:  # noqa: BLE001 — any machine/network failure: log, reconnect with backoff
            log.warning("%s: %s — retrying in %.0f s", src.name, exc, backoff)
            src.close()
            halt.wait(backoff)
            backoff = min(backoff * 2, 60.0)
    src.close()


def push(conf: dict[str, Any], buf: Buffer) -> None:
    ingest = lambda: conf["url"].rstrip("/") + conf.get("ingest_path", "/api/ingest/plant-data")  # noqa: E731 — remote mode may change it
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
                r = s.post(ingest(), data=json.dumps({"agent": agent, "readings": [b for _, b in rows]}), timeout=30,
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


def browse_list(endpoint: str, depth: int = 4, limit: int = 2000) -> list[dict[str, Any]]:
    """The machine's variables under Objects (not the server's own nodes): [{node, name, value}]."""
    from asyncua.sync import Client

    out: list[dict[str, Any]] = []
    with Client(endpoint, timeout=8) as c:
        def walk(node, d, path):
            for ch in node.get_children():
                if len(out) >= limit:
                    return
                try:
                    name = ch.read_browse_name().Name
                    if d == 0 and name == "Server":
                        continue
                    try:
                        v = ch.read_value()
                        if isinstance(v, (int, float, str, bool)):
                            out.append({"node": ch.nodeid.to_string(), "name": ".".join([*path, name]), "value": v})
                    except Exception:  # noqa: BLE001 — objects and folders have no value
                        pass
                    if d < depth:
                        walk(ch, d + 1, [*path, name])
                except Exception:  # noqa: BLE001
                    continue
        walk(c.nodes.objects, 0, [])
    return out


class Remote:
    """Remote mode: machines come from Eurveda Connect (configured in its setup wizard) and are re-read every minute;
    jobs the wizard queues (browse a machine, test-read it) are picked up and answered."""

    def __init__(self, conf: dict[str, Any], buf: Buffer):
        self.conf, self.buf = conf, buf
        self.base = conf["url"].rstrip("/")
        token = conf.get("token") or os.environ.get(conf.get("token_env", "EURVEDA_TOKEN"), "")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "x-nsq-client": "edge-agent"})
        self.config_path = conf.get("config_path", "/api/connect/agent/config")
        self.current: Optional[str] = None
        self.stop_pollers = threading.Event()
        self.threads: list[threading.Thread] = []

    def refresh(self) -> None:
        r = self.s.get(self.base + self.config_path, timeout=20, verify=self.conf.get("verify_tls", True))
        r.raise_for_status()
        cfg = r.json()
        self.conf["ingest_path"] = cfg.get("ingest_path", self.conf.get("ingest_path"))
        self.jobs_path = cfg.get("jobs_path")
        sig = json.dumps(cfg.get("machines"), sort_keys=True)
        if sig == self.current:
            return
        self.stop_pollers.set()
        for t in self.threads:
            t.join(timeout=10)
        self.stop_pollers = threading.Event()
        self.threads = [threading.Thread(target=poll, args=(m, self.buf, False, self.stop_pollers), daemon=True, name=m["name"]) for m in cfg.get("machines", [])]
        for t in self.threads:
            t.start()
        self.current = sig
        log.info("remote config: %d machine(s): %s", len(self.threads), ", ".join(t.name for t in self.threads) or "none yet")

    def run_job(self, j: dict[str, Any]) -> None:
        m = (j.get("request") or {}).get("machine") or {}
        try:
            if j["kind"] == "browse":
                result = {"tags": browse_list(m["endpoint"])}
            else:
                src = make_source(m)
                src.connect()
                try:
                    vals, batch, product = src.read()
                finally:
                    src.close()
                result = {"values": vals, "batch": batch, "product": product}
            status = "done"
        except Exception as exc:  # noqa: BLE001 — report any failure to the wizard
            result, status = {"error": str(exc)[:500]}, "failed"
        self.s.post(f"{self.base}{self.jobs_path}/{j['id']}", json={"status": status, "result": result}, timeout=30)

    def loop(self) -> None:
        last_cfg = 0.0
        while not STOP.is_set():
            try:
                if time.monotonic() - last_cfg > float(self.conf.get("config_every_s", 60)):
                    self.refresh()
                    last_cfg = time.monotonic()
                if getattr(self, "jobs_path", None):
                    for j in self.s.get(self.base + self.jobs_path, timeout=20).json().get("jobs", []):
                        self.run_job(j)
            except Exception as exc:  # noqa: BLE001 — keep trying
                log.warning("remote: %s", exc)
                last_cfg = 0.0
            STOP.wait(5)


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
    if conf.get("remote"):  # machines and jobs from Eurveda Connect
        conf.setdefault("ingest_path", "/api/connect/agent/ingest")
        threads = [threading.Thread(target=Remote(conf, buf).loop, daemon=True, name="remote"),
                   threading.Thread(target=push, args=(conf, buf), daemon=True, name="push")]
        for t in threads:
            t.start()
        log.info("eurveda-agent %s: remote configuration from %s", __version__, conf["url"])
        while not STOP.is_set():
            STOP.wait(1)
        return 0
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
