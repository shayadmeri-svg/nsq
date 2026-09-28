"""Update everything: one DAG that refreshes every dataset the platform holds, in dependency order, and persists it.

Each task says which artifacts it READS and which it WRITES (artifacts are the stores and files on the data map —
see ARTIFACTS, each mapped to its data-map node). Dependencies are derived from that, not written by hand: a task
runs after every task that writes something it reads. A few write-after-write orderings (e.g. the NSQ reload flushes
the namespace the geo map and product ontology live beside) are declared with `after` and shown as such.

Failure rules:
  * a source that cannot be fetched is a warning — its last file stays in use and everything downstream still runs;
  * a hard failure (the NSQ reload, the molecule build, a load) skips only the tasks downstream of it;
  * the persist stage writes portable copies of every store (NSQ snapshot, the whole cdmo:* keyspace — molecules,
    patents, regulatory, demand, plants incl. user plants — and the app's own edits from Postgres), forces Redis to
    disk and, if configured, backs up to Upstash.

The run is one job ("full-refresh") so it shares the runner, logs, audit and confirmation of every other job. Task
progress is written to the log as lines `◆ <task> → <state>`, which the Data jobs page reads to colour the DAG.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .config import settings

# artifact -> (data-map node, label)
ARTIFACTS: dict[str, tuple[str, str]] = {
    "ext:cdsco": ("ext_cdsco", "CDSCO NSQ portal"),
    "pg:app": ("pg_mol", "Postgres: molecules typed in the app, watchlist"),
    "pg:plants": ("pg_plants", "Postgres: user-created plants"),
    "pg:orgs": ("pg_orgs", "Postgres: organisations"),
    "gen:entries": ("f_entries", "watchlist.json + molecules.json"),
    "file:csv": ("f_csv", "Cumulative NSQ CSV"),
    "file:seeds": ("f_seeds", "Curated seed JSON"),
    "file:geo": ("f_geo", "India states GeoJSON"),
    "redis:nsq": ("r_nsq", "Redis nsq:* alerts"),
    "redis:onto_companies": ("r_onto", "Redis manufacturer ontology"),
    "redis:onto_products": ("r_onto", "Redis product ontology"),
    "redis:frame": ("r_frame", "Redis enriched frame"),
    "upstash:nsq": ("ext_upstash", "Upstash (NSQ load target)"),
    "redis:nsq_ready": ("r_nsq", "NSQ data in the server's Redis"),
    "redis:geo": ("r_geo", "Redis geo:india_states"),
    "gen:candidates": ("f_generated", "candidates.json (molecules to look up)"),
    "gen:universe": ("f_generated", "patents / regulatory / demand .json"),
    "redis:cdmo": ("r_cdmo", "Redis cdmo:* molecules, patents, regulatory, demand"),
    "redis:plants": ("r_plant", "Redis cdmo:plant:*"),
    "file:snapshot": ("f_snapshot", "nsq_snapshot.json.gz"),
    "file:cdmo_snapshot": ("f_persist", "cdmo_snapshot.json.gz"),
    "file:app_state": ("f_persist", "generated/app_state.json"),
    "redis:disk": ("r_nsq", "Redis flushed to disk"),
    "ext:upstash": ("ext_upstash", "Upstash backup"),
    "api:caches": ("s_frame", "API caches (frame, forensics, plants)"),
}
_SRC_NODE = {"orange_book": "ext_orange", "purple_book": "ext_purple", "ema": "ext_ema", "clinical_trials": "ext_ct",
             "pubchem": "ext_pubchem", "fda_establishments": "ext_fdasites", "fda_import_alerts": "ext_fdasites",
             "fda_recalls": "ext_fdasites", "cdsco_plants": "ext_cdsco_plants", "eudragmdp": "ext_eudragmdp",
             "fda_inspections": "ext_fda_insp", "fda_dmf": "ext_filings", "edqm_cep": "ext_filings", "ord": "ext_ord",
             "nfhs": "ext_health", "idsp": "ext_health", "comtrade": "ext_comtrade", "cdsco_wc": "ext_cdsco_wc"}

STAGES = [
    ("prepare", "Prepare", "Export the app's own edits so the builds can apply them"),
    ("nsq", "NSQ alerts", "New CDSCO months, reload, ontologies, enriched frame"),
    ("sources", "Public sources", "Every source the server can fetch; a source that is down keeps its last file"),
    ("molecules", "Molecules", "Molecule universe, trial counts, structures, reactions; load patents / regulatory / demand"),
    ("plants", "Plants & maps", "Seeded plants, user plants, the India map"),
    ("persist", "Persist", "Portable copies of every store, Redis to disk, optional Upstash backup"),
    ("serve", "Serve", "Clear and warm the API caches, verify"),
]


@dataclass
class Task:
    id: str
    title: str
    stage: str
    reads: set[str]
    writes: set[str]
    steps: Callable[[dict[str, Any]], list] = lambda p: []
    after: set[str] = field(default_factory=set)  # write-after-write orderings the data flow alone does not show
    soft: bool = False  # failure = warning; downstream still runs on the last good data
    skip: Optional[str] = None  # reason it will not run in this plan
    note: str = ""
    source: Optional[str] = None


def _jobs():
    from . import jobs  # late: jobs imports this module for the registry
    return jobs


# Time budget per source fetch inside Update everything (seconds). A source that runs out keeps its last file, so one
# slow or hanging publisher can never hold the whole refresh hostage.
SOURCE_BUDGET = 15 * 60
_BUDGET = {"cdsco_wc": 45 * 60, "comtrade": 30 * 60, "clinical_trials": 20 * 60, "pubchem": 20 * 60, "ord": 3 * 3600, "eudragmdp": 3 * 3600}
# Scrapes that take hours from a server; off unless asked for (their last pushed file is used)
_SLOW = {"eudragmdp": "EudraGMDP opens every certificate one page at a time — hours from a server"}


def _source_task(k: str, p: dict[str, Any]) -> Task:
    J = _jobs()
    reads = {"gen:candidates"} if k in ("clinical_trials", "pubchem") else set()
    if k == "ord":
        reads = {"src:pubchem"}
    skip = None
    if k == "ord" and not p.get("include_ord"):
        skip = "off: 1.3 GB download and ~1 h scan — tick 'Include the Open Reaction Database'"
    elif k in _SLOW and not p.get("include_slow"):
        skip = (f"off: {_SLOW[k]}; the last pushed file is used — `just fetch-eudragmdp` + `just push-plant-registry` "
                "on a laptop, or tick 'Include slow sources'")
    budget = _BUDGET.get(k, SOURCE_BUDGET)

    def steps(pp: dict[str, Any], k=k):
        s = J._source_steps([k], pp)
        if k in J._NICE:
            s[0].cmd = ["nice", "-n", "15", *s[0].cmd]
        for st in s:
            st.timeout = budget
        return s

    note = f"time budget {budget // 60} min; past it the last file is kept"
    if k in J.LAPTOP and not skip:
        note = f"often refused from a server ({J.LAPTOP[k]['why']}); the last pushed file stays in use · " + note
    return Task(f"src-{k.replace('_', '-')}", J.SOURCE_TITLES[k], "sources" if k not in ("clinical_trials", "pubchem", "ord") else "molecules",
                reads, {f"src:{k}"}, steps, soft=True, skip=skip, note=note, source=k)


def tasks(p: dict[str, Any]) -> list[Task]:
    J = _jobs()
    from .jobs import PY, Step
    local, upstash = J._local(), J._upstash()
    # Everything loads into the server's own Redis (what the site reads). Upstash is only a backup at the end
    # (persist-upstash): loading into it first cost two round trips per record and it closes very large requests.
    target = local
    csv = str(J.DEFAULT_CSV)
    nsq_store = "redis:nsq"
    T: list[Task] = []

    T.append(Task("export-app", "Export app edits (molecules, watchlist)", "prepare", {"pg:app"}, {"gen:entries"},
                  lambda pp: [Step("Export molecules typed in the app and the watchlist", [], fn=J.export_watchlist)]))

    # --- NSQ ------------------------------------------------------------------------------------------------------
    T.append(Task("nsq-fetch", "Fetch new CDSCO months", "nsq", {"ext:cdsco"}, {"file:csv"}, lambda pp: [
        Step("Ensure the cumulative CSV exists (rebuild from Redis if missing)", [PY, "sync_cdsco.py", "--csv", csv, "--redis-url", local, "--bootstrap-only"]),
        Step("Fetch the latest CDSCO month and append new alerts", [PY, "sync_cdsco.py", "--csv", csv, "--redis-url", local, "--exit-unchanged"],
             ok_codes={3}, allow_fail=True)],
        note="nothing new is fine — the reload below still runs from the CSV"))
    T.append(Task("nsq-load", "Reload NSQ alerts + manufacturer ontology", "nsq", {"file:csv"}, {nsq_store, "redis:onto_companies"}, lambda pp: [
        Step("Load CSV into Redis (flush + augment manufacturers)",
             [PY, "load_csv_redis.py", "--input", csv, "--redis-url", target, "--flush", "--augment", "1"])]))
    T.append(Task("nsq-products", "Build product ontology", "nsq", {"file:csv", nsq_store}, {"redis:onto_products"}, lambda pp: [
        Step("Build product ontology", [PY, "build_product_ontology.py", "--input", csv, "--redis-url", target])],
        note="after the reload: the reload flushes the NSQ namespace"))
    T.append(Task("nsq-frame", "Pre-compute enriched frame", "nsq", {nsq_store, "redis:onto_companies", "redis:onto_products"}, {"redis:frame"},
                  lambda pp: [Step("Pre-compute enriched frame", [PY, "build_enriched_frame.py", "--redis-url", target])]))
    T[-1].writes.add("redis:nsq_ready")
    ready = "redis:nsq_ready"
    T.append(Task("nsq-verify", "Verify NSQ data", "nsq", {ready}, set(), lambda pp: [
        Step("Verify", [PY, "verify_nsq_redis.py"], {"REDIS_URL": local})]))

    # --- sources ----------------------------------------------------------------------------------------------------
    for k in J.SOURCE_TITLES:
        T.append(_source_task(k, p))

    # --- molecules --------------------------------------------------------------------------------------------------
    mol_src = {"src:orange_book", "src:purple_book", "src:ema"}
    build = [PY, "build_universe.py", "--redis-url", local]
    T.append(Task("universe-candidates", "Molecule candidates", "molecules", mol_src | {"gen:entries", "file:seeds", ready}, {"gen:candidates"},
                  lambda pp: [Step("Build molecule universe (candidates for trial / structure lookups)", build)]))
    T.append(Task("universe-build", "Build molecule universe", "molecules",
                  mol_src | {"src:clinical_trials", "gen:entries", "file:seeds", ready}, {"gen:universe"},
                  lambda pp: [Step("Build molecule universe (curated seeds + public sources + NSQ ingredients + app edits)", build)],
                  after={"universe-candidates"}))
    gen = lambda n: str(settings.data_dir / "generated" / n)  # noqa: E731
    T.append(Task("load-cdmo", "Load patents, regulatory, demand", "molecules", {"gen:universe"}, {"redis:cdmo"}, lambda pp: [
        Step("Load patents", [PY, "load_patents.py", "--input", gen("patents.json"), "--redis-url", local, "--flush"]),
        Step("Load regulatory passports", [PY, "load_regulatory.py", "--input", gen("regulatory.json"), "--redis-url", local, "--flush"]),
        Step("Load demand profiles", [PY, "load_demand.py", "--input", gen("demand.json"), "--redis-url", local, "--flush"])]))

    # --- plants & maps ----------------------------------------------------------------------------------------------
    T.append(Task("plants-seed", "Load seeded plants (upsert)", "plants", {"file:seeds"}, {"redis:plants"}, lambda pp: [
        Step("Load plant seed (upsert, never flush)", [PY, "load_plant_assets.py", "--input", str(settings.data_dir / "plant_assets_seed.json"), "--redis-url", local])]))
    T.append(Task("plants-user", "Re-publish user plants", "plants", {"pg:plants"}, {"redis:plants"},
                  lambda pp: [Step("Write every user-created plant from Postgres back into Redis", [], fn=J.sync_plants_to_redis)],
                  after={"plants-seed"}, note="after the seed, so a user's edits win over the seeded copy"))
    T.append(Task("geo", "India map (GeoJSON → Redis)", "plants", {"file:geo"}, {"redis:geo"}, lambda pp: [
        Step("Load India states GeoJSON", [PY, "load_geojson_redis.py", "--input", str(settings.data_dir / "geo" / "india_states_slim.geojson"),
                                            "--key", "geo:india_states", "--redis-url", local])],
        after={"nsq-load"}, soft=True, note="after the NSQ reload; the page falls back to the file if this fails"))

    # --- persist ----------------------------------------------------------------------------------------------------
    T.append(Task("persist-nsq", "NSQ snapshot", "persist", {ready, "redis:onto_companies", "redis:onto_products", "redis:geo"}, {"file:snapshot"},
                  lambda pp: [Step("Dump NSQ Redis to the snapshot file", [PY, "dump_snapshot.py", "--redis-url", local, "--output",
                                                                           str(settings.snapshot_path), "--source-label", "full-refresh"])]))
    T.append(Task("persist-cdmo", "Molecules & plants snapshot", "persist", {"redis:cdmo", "redis:plants"}, {"file:cdmo_snapshot"},
                  lambda pp: [Step("Dump every cdmo:* key (molecules, patents, regulatory, demand, plants)", [], fn=dump_cdmo)]))
    T.append(Task("persist-app", "App edits export", "persist", {"pg:app", "pg:plants", "pg:orgs"}, {"file:app_state"},
                  lambda pp: [Step("Export app edits from Postgres (molecules, watchlist, plants, organisations)", [], fn=export_app_state)]))
    T.append(Task("persist-redis", "Redis to disk", "persist", {ready, "redis:frame", "redis:cdmo", "redis:plants", "redis:geo"}, {"redis:disk"},
                  lambda pp: [Step("Force a Redis save (BGSAVE)", [], fn=redis_save)]))
    up_skip = None if (p.get("backup") and upstash) else ("no UPSTASH_URL on the server" if not upstash else "off — tick 'Back up to Upstash'")
    T.append(Task("persist-upstash", "Back up to Upstash", "persist", {"redis:disk"}, {"ext:upstash"}, lambda pp: [
        Step("Copy server Redis → Upstash", [PY, "pull_upstash.py", "--source", local, "--target", upstash or ""])], skip=up_skip))

    # --- serve ------------------------------------------------------------------------------------------------------
    T.append(Task("serve-warm", "Clear & warm API caches", "serve",
                  {"redis:frame", "redis:cdmo", "redis:plants", "redis:geo", "file:snapshot", "file:cdmo_snapshot", "file:app_state",
                   "redis:disk", *(f"src:{k}" for k in J.SOURCE_TITLES)},
                  {"api:caches"}, lambda pp: [Step("Clear caches, rebuild frame, forensics, plant registry and report counts", [], fn=warm)]))
    return T


# --- graph ------------------------------------------------------------------------------------------------------------

def graph(p: dict[str, Any]) -> dict[str, Any]:
    """Tasks with derived dependencies, topological layers and the artifacts on each edge."""
    T = tasks(p)
    by = {t.id: t for t in T}
    writers: dict[str, list[str]] = defaultdict(list)
    for t in T:
        for a in t.writes:
            writers[a].append(t.id)
    deps: dict[str, dict[str, list[str]]] = {t.id: {} for t in T}
    for t in T:
        for a in sorted(t.reads):
            for w in writers.get(a, []):
                if w != t.id:
                    deps[t.id].setdefault(w, []).append(a)
        for w in t.after:
            if w in by:
                deps[t.id].setdefault(w, []).append("(runs after)")
    # Kahn, keeping the declared order inside a layer
    order = {t.id: i for i, t in enumerate(T)}
    indeg = {k: len(v) for k, v in deps.items()}
    children: dict[str, list[str]] = defaultdict(list)
    for k, v in deps.items():
        for u in v:
            children[u].append(k)
    layer_of: dict[str, int] = {}
    frontier = sorted([k for k, n in indeg.items() if n == 0], key=order.get)
    layers: list[list[str]] = []
    while frontier:
        layers.append(frontier)
        nxt = []
        for u in frontier:
            layer_of[u] = len(layers) - 1
            for c in children[u]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    nxt.append(c)
        frontier = sorted(nxt, key=order.get)
    if len(layer_of) != len(T):
        raise ValueError("cycle in the refresh DAG: " + ", ".join(k for k in by if k not in layer_of))
    run_order = [k for layer in layers for k in layer]
    return {
        "tasks": [{"id": t.id, "title": t.title, "stage": t.stage, "reads": sorted(t.reads), "writes": sorted(t.writes),
                   "needs": [{"task": u, "via": via} for u, via in sorted(deps[t.id].items(), key=lambda kv: order[kv[0]])],
                   "layer": layer_of[t.id], "soft": t.soft, "skip": t.skip, "note": t.note, "source": t.source,
                   "node": _SRC_NODE.get(t.source) if t.source else None, "manual": _jobs().manual_for(t.source),
                   "steps": [s.label for s in t.steps(p)] if not t.skip else []} for t in T],
        "order": run_order, "layers": layers,
        "stages": [{"id": s, "title": ti, "hint": h} for s, ti, h in STAGES],
        "artifacts": {a: {"node": n, "label": lbl} for a, (n, lbl) in ARTIFACTS.items()}
        | {f"src:{k}": {"node": "f_sources", "label": f"sources/{k}.json"} for k in _jobs().SOURCE_TITLES},
    }


def descendants(g: dict[str, Any], root: str) -> set[str]:
    kids: dict[str, list[str]] = defaultdict(list)
    for t in g["tasks"]:
        for n in t["needs"]:
            kids[n["task"]].append(t["id"])
    out, stack = set(), [root]
    while stack:
        for c in kids[stack.pop()]:
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


_MARK = re.compile(r"^◆ (\S+) → (running|ok|warn|failed|skipped)(?: · (.*))?$", re.M)


def states_from_log(log: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for m in _MARK.finditer(log or ""):
        out[m.group(1)] = {"state": m.group(2), "note": m.group(3) or ""}
    return out


# --- persistence helpers (run in-process) -----------------------------------------------------------------------------

def _redis():
    import redis
    return redis.Redis.from_url(settings.redis_url)


def _dump_key(r, k: bytes) -> Optional[dict[str, Any]]:
    t = r.type(k).decode()
    dec = lambda b: b.decode("utf-8", errors="replace") if isinstance(b, bytes) else b  # noqa: E731
    if t == "string":
        return {"type": t, "value": dec(r.get(k))}
    if t == "hash":
        return {"type": t, "value": {dec(a): dec(b) for a, b in r.hgetall(k).items()}}
    if t == "set":
        return {"type": t, "value": sorted(dec(x) for x in r.smembers(k))}
    if t == "list":
        return {"type": t, "value": [dec(x) for x in r.lrange(k, 0, -1)]}
    if t == "zset":
        return {"type": t, "value": [[dec(m), s] for m, s in r.zrange(k, 0, -1, withscores=True)]}
    return None


CDMO_SNAPSHOT = lambda: settings.data_dir / "cdmo_snapshot.json.gz"  # noqa: E731


def dump_cdmo() -> str:
    """Every cdmo:* key — molecules, patents, regulatory, demand, complexity, portfolios and plants (user plants too) —
    to one gzip JSON beside the NSQ snapshot, so the molecule side can be restored without rebuilding."""
    r = _redis()
    keys = sorted(r.scan_iter(match="cdmo:*", count=1000))
    out: dict[str, Any] = {}
    kinds: dict[str, int] = defaultdict(int)
    for k in keys:
        v = _dump_key(r, k)
        if v is not None:
            name = k.decode()
            out[name] = v
            kinds[name.split(":")[1] if name.count(":") >= 1 else name] += 1
    doc = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "keys": out}
    path = CDMO_SNAPSHOT()
    tmp = path.with_suffix(".tmp")
    with gzip.GzipFile(tmp, "wb", mtime=0) as fh:
        fh.write(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    tmp.replace(path)
    return f"wrote {len(out)} cdmo keys to {path.name} ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}; {path.stat().st_size // 1024} KB)"


def restore_cdmo() -> str:
    """Upsert the cdmo:* keys from the snapshot file (keys not in the file are left alone)."""
    path = CDMO_SNAPSHOT()
    if not path.exists():
        raise RuntimeError(f"{path.name} not found — run 'Update everything' (or its persist step) first")
    doc = json.loads(gzip.decompress(path.read_bytes()))
    r = _redis()
    pipe = r.pipeline(transaction=False)
    n = 0
    for k, v in doc.get("keys", {}).items():
        t, val = v["type"], v["value"]
        pipe.delete(k)
        if t == "string":
            pipe.set(k, val)
        elif t == "hash" and val:
            pipe.hset(k, mapping=val)
        elif t == "set" and val:
            pipe.sadd(k, *val)
        elif t == "list" and val:
            pipe.rpush(k, *val)
        elif t == "zset" and val:
            pipe.zadd(k, {m: s for m, s in val})
        n += 1
        if n % 500 == 0:
            pipe.execute()
    pipe.execute()
    return f"restored {n} cdmo keys from {path.name} (generated {doc.get('generated_at')})"


def export_app_state() -> str:
    """Everything people changed in the app, as one JSON file: molecules typed in, the watchlist, user plants and
    organisations (their manufacturer keys and plants). Postgres stays the source of truth; this is the portable copy."""
    from sqlalchemy import select

    from .db import SessionLocal
    from .models import MoleculeEntry, Org, Plant, WatchMolecule

    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    with SessionLocal() as db:
        mol = [{"key": e.key, "name": e.name, "added": e.added, "values": e.values or {}, "created_at": iso(e.created_at),
                "updated_at": iso(e.updated_at), "by": e.updated_by or e.created_by} for e in db.scalars(select(MoleculeEntry))]
        watch = [{"name": w.name, "key": w.key, "exclude": w.exclude, "note": w.note, "added_by": w.added_by} for w in db.scalars(select(WatchMolecule))]
        plants = [{"asset_id": p.asset_id, "org_id": p.org_id, "payload": p.payload, "updated_at": iso(p.updated_at)} for p in db.scalars(select(Plant))]
        orgs = [{"id": o.id, "slug": o.slug, "name": o.name, "city": o.city, "country": o.country, "ontology_keys": o.ontology_keys,
                 "plant_ids": o.plant_ids, "is_active": o.is_active} for o in db.scalars(select(Org))]
    out = settings.data_dir / "generated"
    out.mkdir(parents=True, exist_ok=True)
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "molecules": mol, "watchlist": watch, "plants": plants, "orgs": orgs}
    (out / "app_state.json").write_text(json.dumps(doc, indent=1, default=str, ensure_ascii=False))
    return f"exported {len(mol)} molecule entries, {len(watch)} watchlist rows, {len(plants)} user plants, {len(orgs)} organisations"


def redis_save() -> str:
    r = _redis()
    before = r.lastsave()
    try:
        r.bgsave()
    except Exception as exc:  # a save already in progress is fine
        if "in progress" not in str(exc).lower():
            raise
    import time
    for _ in range(60):
        time.sleep(1)
        if r.lastsave() != before:
            break
    info = r.info("persistence")
    return (f"Redis saved at {r.lastsave():%Y-%m-%d %H:%M:%S} · AOF {'on' if info.get('aof_enabled') else 'off'} · "
            f"{r.dbsize():,} keys")


def warm() -> str:
    from . import data, forensics, gaps, plants
    data.invalidate()
    forensics.clear()
    df = data.frame()
    bits = [f"{len(df):,} NSQ alerts in the frame"]
    try:
        bits.append(f"{len(data.cdmo().get('patents') or {}):,} molecules")
    except Exception as exc:
        bits.append(f"molecules: {exc}")
    try:
        bits.append(f"{forensics.overview().get('groups', 0)} forensics product groups")
        gaps.needed()
    except Exception as exc:
        bits.append(f"forensics: {exc}")
    try:
        bits.append(f"{len(plants.registry().get('plants') or {}):,} plants in the registry")
    except Exception as exc:
        bits.append(f"plants: {exc}")
    return "warm: " + " · ".join(bits)
