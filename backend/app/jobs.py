"""Admin job runner: a fixed registry of data operations (the justfile's
data recipes), run as subprocesses with logs persisted to Postgres.

Nothing outside REGISTRY can run — there is no free-text command path.
Each job declares the role it needs and whether it is destructive; the API
enforces both and requires a typed confirmation for destructive runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select

from . import data
from .config import settings
from .db import SessionLocal
from .models import JobRun, Plant, utcnow

PY = sys.executable
UPLOAD_DIR = settings.data_dir / "uploads"
DEFAULT_CSV = settings.data_dir / "CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv"


@dataclass
class Param:
    name: str
    label: str
    kind: str = "bool"  # bool | csv
    default: Any = False
    help: str = ""


@dataclass
class Step:
    label: str
    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    allow_fail: bool = False  # log and continue on a non-zero exit
    ok_codes: set[int] = field(default_factory=set)  # extra exit codes that count as success
    stop_on: dict[int, str] = field(default_factory=dict)  # exit code -> stop here, successfully
    fn: Optional[Callable[[], str]] = None  # run in-process instead of a subprocess (cmd is then ignored)


def _as_step(s) -> Step:
    if isinstance(s, Step):
        return s
    label, cmd, env = s
    return Step(label, cmd, env or {})


@dataclass
class Job:
    key: str
    title: str
    description: str
    group: str
    steps: Callable[[dict[str, Any]], list[tuple[str, list[str], dict[str, str]]]]
    role: str = "admin"  # admin | super_admin
    destructive: Callable[[dict[str, Any]], bool] = lambda p: False
    needs_upstash: bool = False
    params: list[Param] = field(default_factory=list)
    invalidates: bool = True
    after: Optional[Callable[[], str]] = None
    before: Optional[Callable[[], str]] = None
    dag: bool = False  # steps come from pipeline.tasks(), run task by task in dependency order


def _local() -> str:
    return settings.redis_url


def _upstash() -> str:
    return settings.upstash_url


UPLOAD_TYPES = {".csv", ".zip", ".json", ".txt", ".html", ".htm", ".xlsx", ".xls", ".pdf"}


def upload_path(name: str) -> Path:
    path = (UPLOAD_DIR / Path(name).name).resolve()
    if UPLOAD_DIR.resolve() not in path.parents:
        raise ValueError("Invalid upload name.")
    return path


def _csv_path(p: dict[str, Any]) -> Path:
    name = (p.get("csv") or "").strip()
    return upload_path(name) if name else DEFAULT_CSV


def sync_plants_to_redis() -> str:
    """Re-publish every user-created plant from Postgres into Redis."""
    import intelligence_store as store
    from intelligence_models import PlantAsset

    n = 0
    with SessionLocal() as db:
        for row in db.scalars(select(Plant)):
            try:
                store.save_plant_asset(PlantAsset(**row.payload), data.redis_client())
                n += 1
            except Exception as exc:  # keep going; report
                return f"plant {row.asset_id} failed: {exc}"
    return f"re-published {n} user-created plant(s) from Postgres"


def _refresh_steps(p: dict[str, Any], fetch: bool = False):
    csv = str(_csv_path(p))
    target = _upstash() or _local()
    steps: list = []
    if fetch:
        month = (p.get("month") or "").strip()
        backfill = (p.get("backfill_from") or "").strip()
        cmd = [PY, "sync_cdsco.py", "--csv", csv, "--redis-url", _local(), "--exit-unchanged"]
        label = "Fetch the latest CDSCO month and append new alerts to the cumulative CSV"
        if month:
            cmd += ["--month", month]
            label = f"Fetch CDSCO month {month}"
        elif backfill:
            cmd += ["--backfill-from", backfill]
            label = f"Backfill empty CDSCO months since {backfill}"
        steps.append(Step(label, cmd, stop_on={3: "No new CDSCO alerts — Redis left as it is."}))
    else:
        # A fresh box / clone has no CSV (it is gitignored): rebuild it from
        # the records already in Redis instead of failing.
        steps.append(Step("Ensure the cumulative CSV exists (rebuild from Redis if missing)",
                          [PY, "sync_cdsco.py", "--csv", csv, "--redis-url", _local(), "--bootstrap-only"]))
    steps += [
        Step("Load CSV into " + ("Upstash" if _upstash() else "local Redis") + " (flush + ontology augment)",
             [PY, "load_csv_redis.py", "--input", csv, "--redis-url", target, "--flush", "--augment", "1"]),
        Step("Build product ontology", [PY, "build_product_ontology.py", "--input", csv, "--redis-url", target]),
        Step("Pre-compute enriched frame", [PY, "build_enriched_frame.py", "--redis-url", target]),
    ]
    if _upstash():
        steps.append(Step("Copy Upstash → local Redis", [PY, "pull_upstash.py", "--source", _upstash(), "--target", _local()]))
    steps.append(Step("Verify", [PY, "verify_nsq_redis.py"], {"REDIS_URL": _local()}))
    if fetch:
        steps += _universe_steps(p)
    return steps


def export_watchlist() -> str:
    """Write the admin watchlist (Postgres) where build_universe.py reads it."""
    import json as _json

    from .models import WatchMolecule

    from .models import MoleculeEntry

    with SessionLocal() as db:
        rows = [{"name": w.name, "key": w.key, "exclude": w.exclude} for w in db.scalars(select(WatchMolecule))]
        entries = [{"key": e.key, "name": e.name, "added": e.added, "values": e.values or {},
                    "by": e.updated_by or e.created_by,
                    "at": (e.updated_at or e.created_at).date().isoformat() if (e.updated_at or e.created_at) else ""}
                   for e in db.scalars(select(MoleculeEntry))]
    out = settings.data_dir / "generated"
    out.mkdir(parents=True, exist_ok=True)
    (out / "watchlist.json").write_text(_json.dumps(rows, indent=1))
    (out / "molecules.json").write_text(_json.dumps(entries, indent=1, default=str))
    return (f"exported {len(rows)} watchlist entr{'y' if len(rows) == 1 else 'ies'} and "
            f"{len(entries)} molecule{'' if len(entries) == 1 else 's'} entered in the app")


def _gen(name: str) -> str:
    return str(settings.data_dir / "generated" / name)


def _universe_steps(p: dict[str, Any]):
    """Build the molecule universe from seeds + sources + NSQ, then load it."""
    build = [PY, "build_universe.py", "--redis-url", _local()]
    if str(p.get("min_alerts") or "").strip().isdigit():
        build += ["--min-alerts", str(p["min_alerts"]).strip()]
    return [
        # Newly added molecules get trial counts and a structure before the build, so one pass is complete
        Step("Trial counts for new molecules (ClinicalTrials.gov)", [PY, "fetch_source.py", "clinical_trials", "--missing-only"], allow_fail=True, ok_codes={3}),
        Step("Structures for new molecules (PubChem)", [PY, "fetch_source.py", "pubchem", "--missing-only"], allow_fail=True, ok_codes={3}),
        Step("Build molecule universe (curated seeds + public sources + NSQ ingredients)", build),
        Step("Load patents", [PY, "load_patents.py", "--input", _gen("patents.json"), "--redis-url", _local(), "--flush"]),
        Step("Load regulatory passports", [PY, "load_regulatory.py", "--input", _gen("regulatory.json"), "--redis-url", _local(), "--flush"]),
        Step("Load demand profiles", [PY, "load_demand.py", "--input", _gen("demand.json"), "--redis-url", _local(), "--flush"]),
    ]


def _source_steps(keys: list[str], p: dict[str, Any]):
    steps = []
    for k in keys:
        cmd = [PY, "fetch_source.py", k] + (["--force"] if p.get("force") else [])
        steps.append(Step(f"Fetch {SOURCE_TITLES.get(k, k)}", cmd, allow_fail=True, ok_codes={3}))
    return steps


def _sync_all_steps(p: dict[str, Any]):
    first = [k for k in SOURCE_TITLES if k not in ("clinical_trials", "pubchem") and k not in _NOT_ON_SERVER]
    steps = _source_steps(first, p)
    # candidates.json must exist before ClinicalTrials.gov is queried
    steps.append(Step("Build molecule universe (candidates for trial lookups)", [PY, "build_universe.py", "--redis-url", _local()]))
    steps += _source_steps(["clinical_trials", "pubchem"], p)
    steps += _universe_steps(p)
    if p.get("backup") and _upstash():
        steps.append(Step("Back up to Upstash", [PY, "pull_upstash.py", "--source", _local(), "--target", _upstash()]))
    return steps


def _seed_steps(p: dict[str, Any]):
    # Curated seeds go through the universe builder so public-source overlays
    # and auto-discovered molecules survive a seed reload.
    steps = _universe_steps(p)
    # Never --flush plants: that would delete user-created plant profiles.
    steps.append(Step("Load plant seed (upsert)", [PY, "load_plant_assets.py", "--input", str(settings.data_dir / "plant_assets_seed.json"), "--redis-url", _local()]))
    return steps


SOURCE_TITLES = {
    "orange_book": "FDA Orange Book",
    "purple_book": "FDA Purple Book",
    "ema": "EMA medicines (EPAR)",
    "fda_establishments": "FDA establishment registrations (India)",
    "fda_import_alerts": "FDA Import Alert 66-40 (India)",
    "fda_recalls": "openFDA recalls (India)",
    "clinical_trials": "ClinicalTrials.gov trial counts",
    "pubchem": "PubChem structures & melting points",
    "cdsco_plants": "CDSCO plant registry (WHO-GMP + SUGAM)",
    "cdsco_wc": "CDSCO Written Confirmations (API exports to EU)",
    "eudragmdp": "EU GMP certificates (EudraGMDP, India)",
    "fda_inspections": "FDA inspection classifications (India)",
    "fda_dmf": "FDA Drug Master Files (Type II)",
    "edqm_cep": "EDQM Certificates of Suitability (CEP)",
    "ord": "Open Reaction Database (how molecules are made)",
    "nfhs": "NFHS district fact sheets",
    "idsp": "IDSP weekly outbreaks",
    "comtrade": "UN Comtrade — India pharma trade",
}
_SOURCE_JOB_DESC = {
    "orange_book": "US patents, exclusivity, RLD/TE codes and ANDA competitors per ingredient. Rebuilds the molecule universe after.",
    "purple_book": "Licensed biologics, reference-product exclusivity and biosimilar counts. Rebuilds the molecule universe after.",
    "ema": "EU central authorisations, generics/biosimilars and therapeutic areas. Rebuilds the molecule universe after.",
    "clinical_trials": "Trial totals, phase 3+, recent starts and India sites per molecule (60 molecules per run, oldest first; each is re-checked weekly).",
    "pubchem": "SMILES, XLogP3 and experimental melting points per molecule for the lab (80 per run; each re-checked monthly).",
    "fda_establishments": "Every FDA-registered establishment in India (FEI, DUNS, operations) — feeds the site directory.",
    "cdsco_plants": "CDSCO's approved manufacturing sites (SUGAM) and WHO-GMP certified units with what each is permitted to make — the plant registry. CDSCO often refuses cloud servers: run it on a laptop in India, or upload the WHO-GMP PDF here.",
    "cdsco_wc": "CDSCO International Cell: every Written Confirmation for API exports to the EU (~700 letters since 2013) with its PDF — Playground · Written confirmations. CDSCO refuses cloud servers: run just fetch-cdsco-wc on a laptop, then just push-wc (PDFs ~2.7 GB).",
    "eudragmdp": "Every EU GMP certificate and statement of non-compliance for Indian sites, with the approved operations (Union coded scope) — stated capabilities and EU status in the plant registry. Needs a network EudraGMDP answers (a laptop works).",
    "fda_inspections": "Every FDA drug / biologic inspection of an Indian site with its outcome (NAI / VAI / OAI) — US FDA status in the plant registry. Needs FDA_DD_USER / FDA_DD_KEY (Data Dashboard API access) in the server's .env, or upload the Inspections table exported to Excel.",
    "fda_dmf": "FDA's quarterly list of Drug Master Files: active Type II (drug substance) holders per API — 'Who can make it' → API filings. Upload the .xls if FDA blocks the server.",
    "edqm_cep": "EDQM's CEP data file: valid Certificates of Suitability per substance and holder — 'Who can make it' → API filings. If the link is not found, download 'CEP data file' from the EDQM CEP database page and upload it.",
    "ord": "Scans the Open Reaction Database (~1.3 GB, 1.8 M patent reactions) for reactions that make tracked molecules (their structures come from PubChem): conditions, solvents, catalysts and what they demand of an API plant (hydrogenation, cryogenic, pressure, hazardous reagents). Runs on the server at low CPU priority: the first run downloads 1.3 GB into data/raw/ord and scans for about an hour; later runs download only changed files. Monthly schedule available (off by default).",
    "nfhs": "54 NFHS indicators by district / state and survey round — diabetes and blood pressure (incl. severe), obesity, anaemia (women, pregnant, girls, children) and iron-folic acid use, child nutrition, vaccination, diarrhoea / ARI and their treatment (ORS, zinc), C-sections and institutional births, contraception, insurance and out-of-pocket spend, cancer screening, tobacco / alcohol — each with the medicines it moves. Playground · Health & trade. Downloads open extracts of the NFHS-5 fact sheets (NFHS-4 alongside); upload a table to add NFHS-6.",
    "idsp": "Outbreaks reported to IDSP each week (state, district, disease, cases, deaths), parsed from the weekly PDFs — latest 26 weeks. Upload PDFs if the site refuses the server.",
    "comtrade": "India's exports and imports of pharmaceutical HS codes by partner, last 6 years (UN Comtrade; COMTRADE_KEY for the full API).",
    "fda_import_alerts": "Indian firms on the drug-GMP red list — feeds the site directory.",
    "fda_recalls": "US recalls of drugs made by Indian firms — feeds the site directory.",
}
_MOLECULE_SOURCES = {"orange_book", "purple_book", "ema", "clinical_trials"}

# Sources the server cannot fetch (the publisher refuses cloud networks, needs a key, or the download is too big for
# the server): run the recipe on a laptop, then push the file. The server's daily sync skips the heavy ones.
LAPTOP: dict[str, dict[str, str]] = {
    "cdsco_plants": {"fetch": "just fetch-plants", "push": "just push-plant-registry HOST KEY", "why": "CDSCO refuses cloud servers"},
    "eudragmdp": {"fetch": "just fetch-eudragmdp", "push": "just push-plant-registry HOST KEY", "why": "EudraGMDP refuses cloud servers"},
    "fda_dmf": {"fetch": "just fetch-fda-dmf FILE", "push": "just push-plant-registry HOST KEY", "why": "FDA blocks automated downloads of the DMF list"},
    "edqm_cep": {"fetch": "just fetch-cep", "push": "just push-plant-registry HOST KEY", "why": "EDQM's file is easier from a browser session"},
    "cdsco_wc": {"fetch": "just fetch-cdsco-wc", "push": "just push-wc HOST KEY", "why": "CDSCO refuses cloud servers; the letters are ~2.7 GB of PDFs"},
    "idsp": {"fetch": "just fetch-idsp", "push": "just push-signals HOST KEY", "why": "Indian government sites (NCDC, which now hosts the IDSP reports) often refuse cloud servers"},
}
# When the server cannot download a source, the file can be fetched in a browser and uploaded (Data jobs → Upload data
# file), then picked in the source job's file field. What to download, where, and in which format:
MANUAL: dict[str, dict[str, Any]] = {
    "orange_book": {"file": "Orange Book data files (zip with products.txt, patent.txt, exclusivity.txt)", "accepts": ".zip",
                    "links": [("FDA · Orange Book data files", "https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files"),
                              ("Direct download (zip)", "https://www.fda.gov/media/76860/download")],
                    "steps": ["Open the data-files page and download the compressed (.zip) data files", "Upload the .zip unchanged"]},
    "purple_book": {"file": "Purple Book monthly data download (CSV)", "accepts": ".csv",
                    "links": [("FDA · Purple Book downloads", "https://purplebooksearch.fda.gov/downloads")],
                    "steps": ["Pick the latest month under 'Data download'", "Upload the CSV"]},
    "ema": {"file": "EMA medicines report (JSON)", "accepts": ".json",
            "links": [("EMA · Download medicine data", "https://www.ema.europa.eu/en/medicines/download-medicine-data"),
                      ("Direct download (JSON)", "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json")],
            "steps": ["Download 'Medicines' in JSON format", "Upload the .json"]},
    "fda_establishments": {"file": "Drug establishments current registration (DECRS) — drls_reg.zip or drls_reg.txt", "accepts": ".zip, .txt",
                           "links": [("FDA · Drug establishments current registration site", "https://www.fda.gov/drugs/drug-approvals-and-databases/drug-establishments-current-registration-site"),
                                     ("Direct download (zip)", "https://www.accessdata.fda.gov/cder/drls_reg.zip")],
                           "steps": ["Download the registration file", "Upload the .zip (or the .txt inside it)"]},
    "fda_import_alerts": {"file": "Import Alert 66-40 page for India, saved as HTML", "accepts": ".html",
                          "links": [("FDA · Import Alert 66-40", "https://www.accessdata.fda.gov/cms_ia/importalert_189.html")],
                          "steps": ["Open the page in a browser", "File → Save Page As… (HTML only)", "Upload the .html"]},
    "fda_recalls": {"file": "openFDA drug enforcement results for India (JSON)", "accepts": ".json",
                    "links": [("openFDA · drug enforcement API", "https://open.fda.gov/apis/drug/enforcement/"),
                              ("Query for Indian firms (JSON)", "https://api.fda.gov/drug/enforcement.json?search=country:%22India%22&limit=1000")],
                    "steps": ["Open the query link and save the JSON", "Upload the .json"]},
    "cdsco_plants": {"file": "CDSCO WHO-GMP certified units list (PDF)", "accepts": ".pdf",
                     "links": [("CDSCO · WHO-GMP data (latest known)", "https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadIndustryCommon/Final%20WHO%20GMP%20data%20for%20website%2011.09.2025.pdf"),
                               ("CDSCO · WHO-GMP CoPP list", "https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadIndustryCommon/WHO%20GMP%20CoPP%20list24.pdf"),
                               ("SUGAM · approved manufacturing sites", "https://cdscoonline.gov.in/CDSCO/manuf_site")],
                     "steps": ["CDSCO often refuses servers outside India: download the WHO-GMP PDF in a browser",
                               "If the link is dead, search cdsco.gov.in for 'WHO GMP data for website'", "Upload the .pdf"]},
    "eudragmdp": {"file": "EudraGMDP GMP certificates / non-compliance for India", "accepts": "laptop run",
                  "links": [("EudraGMDP · GMP compliance search", "https://eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPCompliance.do")],
                  "steps": ["EudraGMDP has no export file: run `just fetch-eudragmdp` on a laptop", "then `just push-plant-registry HOST KEY`"]},
    "fda_inspections": {"file": "FDA Data Dashboard inspections table (Country = India, Product Type = Drugs + Biologics), exported to Excel", "accepts": ".xlsx, .csv",
                        "links": [("FDA Data Dashboard · Inspections", "https://datadashboard.fda.gov/oii/cd/inspections.htm"),
                                  ("Or request an API key (FDA_DD_USER / FDA_DD_KEY)", "https://datadashboard.fda.gov/oii/api/index.htm")],
                        "steps": ["Filter Country = India, Product Type = Drugs (and Biologics)", "Export → Excel", "Upload the .xlsx"]},
    "fda_dmf": {"file": "FDA list of Drug Master Files (quarterly Excel)", "accepts": ".xls, .xlsx",
                "links": [("FDA · List of Drug Master Files", "https://www.fda.gov/drugs/drug-master-files-dmfs/list-drug-master-files-dmfs")],
                "steps": ["Download the current 'List of DMFs' Excel file", "Upload it unchanged"]},
    "edqm_cep": {"file": "EDQM CEP data file", "accepts": ".xlsx, .csv, .txt",
                 "links": [("EDQM · Certification database (CEP)", "https://extranet.edqm.eu/publications/recherches_CEP.shtml")],
                 "steps": ["Open the CEP database page", "Click 'Download CEP data file'", "Upload the file"]},
    "idsp": {"file": "IDSP / NCDC weekly outbreak reports (PDF, one per week)", "accepts": ".pdf",
             "links": [("NCDC · Weekly outbreaks", "https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php"),
                       ("IDSP · weekly reports (old site)", "https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=406&lid=3689")],
                 "steps": ["Download the latest weekly PDFs", "Upload each PDF and run the source with it (or `just fetch-idsp` + `just push-signals` for many weeks)"]},
    "nfhs": {"file": "NFHS fact-sheet table (NFHS-5 districts CSV, or an NFHS-6 table)", "accepts": ".csv, .xlsx",
             "links": [("NFHS-5 fact sheets (CSV extracts)", "https://github.com/jvargh7/nfhs5_factsheets"),
                       ("IIPS · NFHS releases", "https://www.nfhsiips.in/nfhsuser/release-details.php")],
             "steps": ["Download a districts / states table", "Upload it to add a round"]},
    "comtrade": {"file": "UN Comtrade needs an API key rather than a file", "accepts": "COMTRADE_KEY in .env",
                 "links": [("UN Comtrade developer portal (free key)", "https://comtradedeveloper.un.org/"),
                           ("UN Comtrade Plus", "https://comtradeplus.un.org/")],
                 "steps": ["Sign up, subscribe to 'comtrade - v1'", "Put the primary key in the server's .env as COMTRADE_KEY", "Restart with ./deploy.sh"]},
    "cdsco_wc": {"file": "Written Confirmation letters (~700 PDFs, ~2.7 GB)", "accepts": "laptop run",
                 "links": [("CDSCO · International Cell", "https://cdsco.gov.in/opencms/opencms/en/International-cell1/")],
                 "steps": ["Run `just fetch-cdsco-wc` on a laptop in India", "then `just push-wc HOST KEY`"]},
}


def manual_for(key: Optional[str]) -> Optional[dict[str, Any]]:
    m = MANUAL.get(key or "")
    return {**m, "links": [{"label": a, "url": b} for a, b in m["links"]]} if m else None


# never in the daily sync-sources: the WC letters are ~2.7 GB (laptop only), ORD is a 1.3 GB download and a ~1 h scan
# (it has its own monthly schedule, off by default, and runs at low CPU priority)
_NOT_ON_SERVER = {"ord", "cdsco_wc"}
_NICE = {"ord"}  # long CPU-bound scans: run under `nice` so the site stays responsive on a small server


def source_status(key: str) -> dict[str, Any]:
    """What we hold for a source: the manifest entry (written where it was fetched) plus the file itself — a file pushed
    from a laptop has no manifest entry on the server, so its own header (retrieved_at, records) is read."""
    import json as _json
    import re as _re

    d = settings.data_dir / "sources"
    try:
        m = (_json.loads((d / "manifest.json").read_text(encoding="utf-8")) or {}).get(key) or {}
    except (OSError, ValueError):
        m = {}
    f = d / f"{key}.json"
    out: dict[str, Any] = {"status": m.get("status"), "error": m.get("error") or None, "last_attempt": m.get("last_attempt"),
                           "last_success": m.get("last_success"), "records": m.get("records"), "file": None}
    if f.exists():
        st = f.stat()
        with open(f, "rb") as fh:
            head = fh.read(2048).decode("utf-8", errors="ignore")
        got = dict(_re.findall(r'"(retrieved_at|records)":\s*"?([^",}]+)"?', head))
        out["file"] = {"bytes": st.st_size, "retrieved_at": got.get("retrieved_at")}
        out["records"] = int(got["records"]) if str(got.get("records", "")).isdigit() else out["records"]
        out["last_success"] = max(filter(None, [out["last_success"], got.get("retrieved_at")]), default=None)
    if key == "cdsco_wc":
        docs = settings.data_dir / "docs" / "cdsco_wc"
        out["pdfs"] = sum(1 for _ in docs.glob("*.pdf")) if docs.exists() else 0
    out["state"] = ("failing" if out["status"] in ("error", "unreachable") and not out["file"] else
                    "stale" if out["status"] in ("error", "unreachable") else "ok" if out["file"] else "missing")
    return out


def _one_source(k: str):
    def steps(p: dict[str, Any]):
        s = _source_steps([k], p)
        s[0].allow_fail = False
        if k in _NICE:
            s[0].cmd = ["nice", "-n", "15", *s[0].cmd]
        if (p.get("file") or "").strip():
            s[0].cmd += ["--from-file", str(upload_path(p["file"]))]
            s[0].label += " (from uploaded file)"
        if k in ("clinical_trials", "pubchem"):
            s.insert(0, Step("Refresh molecule candidates", [PY, "build_universe.py", "--redis-url", _local()]))
        if k in _MOLECULE_SOURCES:
            s += _universe_steps(p)
        return s
    return steps


REGISTRY: dict[str, Job] = {j.key: j for j in [
    Job("ping", "Check Redis", "Ping the in-server Redis and report the key count.", "Health",
        lambda p: [("Ping", [PY, "ping_redis.py"], {"REDIS_URL": _local()})], invalidates=False),
    Job("verify", "Verify NSQ data", "Count loaded NSQ records and print a sample.", "Health",
        lambda p: [("Verify", [PY, "verify_nsq_redis.py"], {"REDIS_URL": _local()})], invalidates=False),
    Job("pull-upstash", "Pull from Upstash", "Copy the NSQ dataset and CDMO seeds from Upstash into the in-server Redis.",
        "Sync", lambda p: [("Pull", [PY, "pull_upstash.py", "--source", _upstash(), "--target", _local()] + (["--dry-run"] if p.get("dry_run") else []), {})],
        destructive=lambda p: not p.get("dry_run"), needs_upstash=True,
        params=[Param("dry_run", "Dry run (show what would change)", default=True)]),
    Job("backup-to-upstash", "Back up to Upstash", "Copy the in-server Redis (NSQ data + CDMO incl. user plants) up to Upstash.",
        "Sync", lambda p: [("Push", [PY, "pull_upstash.py", "--source", _local(), "--target", _upstash()] + (["--dry-run"] if p.get("dry_run") else []), {})],
        destructive=lambda p: not p.get("dry_run"), needs_upstash=True, invalidates=False,
        params=[Param("dry_run", "Dry run (show what would change)", default=True)]),
    Job("restore-snapshot", "Restore from snapshot", "Load the bundled snapshot file into the in-server Redis (use when Upstash is unavailable).",
        "Sync", lambda p: [("Restore", [PY, "restore_snapshot.py", "--input", str(settings.snapshot_path), "--redis-url", _local()] + (["--flush"] if p.get("flush") else []), {}),
                           ("Pre-compute enriched frame", [PY, "build_enriched_frame.py", "--redis-url", _local()], {})],
        destructive=lambda p: bool(p.get("flush")),
        params=[Param("flush", "Delete existing nsq:* / geo:* keys first", default=False)]),
    Job("build-frame", "Rebuild enriched frame", "Recompute the precomputed dashboard frame from the records in Redis.",
        "Data", lambda p: [("Build", [PY, "build_enriched_frame.py", "--redis-url", _local()], {})]),
    Job("snapshot", "Write snapshot", "Dump the in-server Redis to the snapshot file (the fallback tier).",
        "Data", lambda p: [("Dump", [PY, "dump_snapshot.py", "--redis-url", _local(), "--output", str(settings.snapshot_path), "--source-label", "server"], {})],
        invalidates=False),
    Job("refresh-nsq", "Monthly NSQ refresh", "Rebuild the whole NSQ dataset from a CSV: load, ontologies, frame, then copy to the in-server Redis.",
        "Data", _refresh_steps, role="super_admin", destructive=lambda p: True,
        params=[Param("csv", "CSV file (blank = bundled cumulative CSV)", kind="csv", default="")]),
    Job("fetch-nsq", "Fetch latest CDSCO month", "Check the live CDSCO NSQ table; when it has new alerts, append them to the cumulative CSV, reload NSQ data and rebuild the molecule universe. Does nothing when there is nothing new.",
        "Pipelines", lambda p: _refresh_steps({**p, "csv": ""}, fetch=True), role="super_admin", destructive=lambda p: True,
        before=export_watchlist,
        params=[Param("month", "Only this reporting month (YYYY-MM, blank = current)", kind="text", default=""),
                Param("backfill_from", "Or backfill every empty month since (YYYY-MM)", kind="text", default="")]),
    Job("sync-sources", "Sync all public sources", "Fetch every public source the server can reach (FDA Orange / Purple Book, EMA, FDA site records, recalls and import alerts, ClinicalTrials.gov, PubChem, UN Comtrade, and a try at the ones that often refuse servers), then rebuild and load the molecule universe. A source that is down is skipped and its last file stays in use. The Open Reaction Database and the Written Confirmation PDFs are never fetched here: they are laptop jobs.",
        "Pipelines", _sync_all_steps, before=export_watchlist,
        params=[Param("force", "Re-download even if unchanged", default=False),
                Param("backup", "Back up to Upstash afterwards", default=False)]),
    Job("build-universe", "Rebuild molecule universe", "Recombine curated seeds, the last fetched sources, NSQ ingredients and the watchlist, then load patents / regulatory / demand into Redis. No downloads.",
        "Pipelines", _universe_steps, before=export_watchlist,
        params=[Param("min_alerts", "Min NSQ alerts for an auto molecule (blank = 5)", kind="text", default="")]),
    *[Job(f"src-{k.replace('_', '-')}", SOURCE_TITLES[k], _SOURCE_JOB_DESC[k], "Sources", _one_source(k),
          before=export_watchlist if k in _MOLECULE_SOURCES else None, invalidates=k in _MOLECULE_SOURCES,
          params=[Param("force", "Re-download even if unchanged", default=False),
                  Param("file", "Or parse an uploaded file (for when the server cannot reach the source)", kind="file", default="")])
      for k in SOURCE_TITLES],
    Job("plant-registry", "Rebuild plant registry", "Fetch everything the plant registry is built from: CDSCO's approved sites + WHO-GMP list, EU GMP certificates (EudraGMDP), FDA inspection outcomes (needs the Data Dashboard API key), FDA registrations and the Import Alert 66-40 red list. The Plants tab, the workbench and site matches pick the new files up on their own. CDSCO / EudraGMDP often refuse cloud servers — then run `just fetch-plant-registry` and `just fetch-fda-sites` on a laptop and `just push-plant-registry`.",
        "Sources", lambda p: _source_steps(["cdsco_plants", "eudragmdp", "fda_inspections", "fda_establishments", "fda_import_alerts"], p), invalidates=False,
        params=[Param("force", "Re-download even if unchanged", default=False)]),
    Job("load-seeds", "Reload CDMO seeds", "Rebuild the molecule universe from data/*.json seeds (+ fetched sources) and reload seeded plants. User plants are kept.",
        "Data", _seed_steps, role="super_admin", destructive=lambda p: True, before=export_watchlist, after=sync_plants_to_redis),
    Job("sync-plants", "Re-publish user plants", "Write every user-created plant from Postgres back into Redis.",
        "Data", lambda p: [], after=sync_plants_to_redis),
    Job("restore-cdmo", "Restore molecules & plants snapshot", "Load data/cdmo_snapshot.json.gz (written by Update everything) back into Redis: molecules, patents, regulatory, demand and plants. Keys not in the file are left alone.",
        "Sync", lambda p: [Step("Restore cdmo:* keys from the snapshot", [], fn=_restore_cdmo)], role="super_admin", destructive=lambda p: True),
    Job("full-refresh", "Update everything", "One run that refreshes every dataset in dependency order — new CDSCO months and the NSQ reload, every public source, the molecule universe (trials, structures, patents, regulatory, demand), plants and the India map — then persists portable copies of every store and warms the caches. Upstream / downstream order comes from the data map; a source that is down keeps its last file, and a hard failure skips only what depends on it.",
        "Pipelines", lambda p: [], role="super_admin", destructive=lambda p: True, dag=True,
        params=[Param("force", "Re-download sources even if unchanged", default=False),
                Param("include_ord", "Include the Open Reaction Database (1.3 GB, ~1 h)", default=False),
                Param("backup", "Back up to Upstash at the end", default=False)]),
]}


def _restore_cdmo() -> str:
    from . import pipeline
    return pipeline.restore_cdmo()

# Jobs a schedule may run, with their default schedule (IST).
SCHEDULABLE: dict[str, dict[str, Any]] = {
    "fetch-nsq": {"enabled": True, "frequency": "daily", "hour": 6, "minute": 30},
    "sync-sources": {"enabled": True, "frequency": "daily", "hour": 2, "minute": 30},
    "build-universe": {"enabled": False, "frequency": "daily", "hour": 3, "minute": 45},
    "src-orange-book": {"enabled": False, "frequency": "weekly", "hour": 3, "minute": 0, "weekday": 0},
    "src-ema": {"enabled": False, "frequency": "daily", "hour": 3, "minute": 15},
    "src-purple-book": {"enabled": False, "frequency": "monthly", "hour": 3, "minute": 30, "day": 5},
    "src-clinical-trials": {"enabled": False, "frequency": "daily", "hour": 4, "minute": 0},
    "src-pubchem": {"enabled": False, "frequency": "daily", "hour": 4, "minute": 10},
    "src-fda-establishments": {"enabled": False, "frequency": "weekly", "hour": 4, "minute": 30, "weekday": 6},
    "src-fda-import-alerts": {"enabled": False, "frequency": "daily", "hour": 4, "minute": 45},
    "src-fda-recalls": {"enabled": False, "frequency": "weekly", "hour": 5, "minute": 0, "weekday": 6},
    "src-fda-inspections": {"enabled": False, "frequency": "weekly", "hour": 5, "minute": 15, "weekday": 6},
    "src-ord": {"enabled": False, "frequency": "monthly", "hour": 1, "minute": 0, "day": 2},
    "build-frame": {"enabled": False, "frequency": "daily", "hour": 5, "minute": 30},
    "snapshot": {"enabled": False, "frequency": "weekly", "hour": 5, "minute": 45, "weekday": 6},
    "backup-to-upstash": {"enabled": False, "frequency": "daily", "hour": 7, "minute": 0, "params": {"dry_run": False}},
    "full-refresh": {"enabled": False, "frequency": "weekly", "hour": 1, "minute": 30, "weekday": 6},
}


_SOURCE_OF_JOB = {f"src-{k.replace('_', '-')}": k for k in SOURCE_TITLES}


def describe(job: Job) -> dict[str, Any]:
    src = _SOURCE_OF_JOB.get(job.key)
    return {
        "source": src, "laptop": LAPTOP.get(src) if src else None, "manual": manual_for(src),
        "schedule": SCHEDULABLE.get(job.key),
        "key": job.key, "title": job.title, "description": job.description, "group": job.group,
        "role": job.role, "needs_upstash": job.needs_upstash,
        "available": (not job.needs_upstash) or bool(_upstash()),
        "params": [p.__dict__ for p in job.params],
        "destructive_by_default": job.destructive({p.name: p.default for p in job.params}),
    }


# --- runner --------------------------------------------------------------------

_running: dict[str, int] = {}  # job_key -> run id
_running_lock = threading.Lock()
_live_logs: dict[int, list[str]] = {}


def is_running(key: str) -> Optional[int]:
    with _running_lock:
        return _running.get(key)


def live_log(run_id: int) -> Optional[str]:
    buf = _live_logs.get(run_id)
    return "".join(buf) if buf is not None else None


def _redact(line: str) -> str:
    for secret in filter(None, [settings.upstash_url]):
        line = line.replace(secret, "rediss://***")
    for name in ("FDA_DD_USER", "FDA_DD_KEY", "COMTRADE_KEY"):  # source keys never reach a job log
        v = os.environ.get(name)
        if v and len(v) > 3:
            line = line.replace(v, "***")
    return line


def launch(job: Job, params: dict[str, Any], started_by: Optional[int], email: str) -> JobRun:
    """Create a JobRun row and start it (used by the API and the scheduler)."""
    with SessionLocal() as db:
        run = JobRun(job_key=job.key, params=params, status="queued", started_by=started_by, started_by_email=email)
        db.add(run)
        db.commit()
        db.refresh(run)
        db.expunge(run)
    try:
        start(job, params, run)
    except RuntimeError:
        with SessionLocal() as db:
            r = db.get(JobRun, run.id)
            r.status, r.log = "failed", "Another run of this job is in progress."
            db.commit()
        raise
    return run


_READ_ONLY = {"ping", "verify"}


def start(job: Job, params: dict[str, Any], run: JobRun) -> None:
    with _running_lock:
        if job.key in _running:
            raise RuntimeError("already running")
        # Update everything owns every store while it runs; it waits for nothing and nothing interleaves with it
        if "full-refresh" in _running and job.key not in _READ_ONLY:
            raise RuntimeError("Update everything is running")
        if job.dag and any(k not in _READ_ONLY for k in _running):
            raise RuntimeError("other jobs are running: " + ", ".join(_running))
        _running[job.key] = run.id
    _live_logs[run.id] = []
    threading.Thread(target=_execute, args=(job, params, run.id), daemon=True, name=f"job-{job.key}-{run.id}").start()


def _run_step(st: Step, emit: Callable[[str], None], base_env: dict[str, str]) -> int:
    """One step: an in-process function or a subprocess in redis-loader/. Returns the exit code."""
    t0 = time.time()
    if st.fn is not None:
        try:
            emit(f"  {st.fn()}\n")
            code = 0
        except Exception as exc:
            emit(f"  ERROR: {exc}\n")
            code = 1
    else:
        proc = subprocess.Popen(st.cmd, cwd=str(settings.loader_dir), env={**base_env, **st.env},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            emit(line)
        code = proc.wait()
    emit(f"  exit {code} · {time.time() - t0:.1f}s\n")
    return code


def _execute_dag(params: dict[str, Any], emit: Callable[[str], None]) -> tuple[str, int]:
    """Run pipeline.tasks() in topological order. A soft task's failure is a warning; a hard failure skips the tasks
    downstream of it. Progress lines `◆ <task> → <state>` let the Data jobs page colour the graph."""
    from . import pipeline

    g = pipeline.graph(params)
    by = {t.id: t for t in pipeline.tasks(params)}
    base_env = {**os.environ, "PYTHONUNBUFFERED": "1", "REDIS_URL": _local(), "DATA_DIR": str(settings.data_dir)}
    blocked: dict[str, str] = {}
    warned, failed, done = [], [], 0
    emit(f"Update everything · {len(g['order'])} tasks in {len(g['layers'])} layers\n")
    for tid in g["order"]:
        t = by[tid]
        if t.skip:
            emit(f"\n◆ {tid} → skipped · {t.skip}\n")
            continue
        if tid in blocked:
            emit(f"\n◆ {tid} → skipped · upstream {blocked[tid]} failed\n")
            continue
        emit(f"\n◆ {tid} → running\n")
        state = "ok"
        steps = [_as_step(x) for x in t.steps(params)]
        for i, st in enumerate(steps, 1):
            emit(f"▶ [{t.title} {i}/{len(steps)}] {st.label}\n")
            code = _run_step(st, emit, base_env)
            if code == 0 or code in st.ok_codes:
                continue
            if code in st.stop_on:
                emit(f"■ {st.stop_on[code]}\n")
                break
            if st.allow_fail or t.soft:
                state = "warn"
                emit("  ↳ continuing without it\n")
                if not st.allow_fail:
                    break
                continue
            state = "failed"
            break
        done += 1
        if state == "failed":
            failed.append(t.title)
            for d in pipeline.descendants(g, tid):
                blocked.setdefault(d, t.title)
        elif state == "warn":
            warned.append(t.title)
        emit(f"◆ {tid} → {state}\n")
    if failed:
        emit("\n✖ Failed: " + ", ".join(failed) + (f" · {len(blocked)} downstream task(s) skipped" if blocked else "") + "\n")
    if warned:
        emit("⚠ Kept the last good data for: " + ", ".join(warned) + "\n")
    if not failed:
        emit(f"\n✔ Everything updated and persisted ({done} tasks run).\n")
    return ("failed" if failed else "partial" if warned else "succeeded"), (1 if failed else 0)


def _execute(job: Job, params: dict[str, Any], run_id: int) -> None:
    buf = _live_logs[run_id]

    def emit(s: str) -> None:
        buf.append(_redact(s))

    status, code = "succeeded", 0
    with SessionLocal() as db:
        run = db.get(JobRun, run_id)
        run.status, run.started_at = "running", utcnow()
        db.commit()
    try:
        if job.dag:
            status, code = _execute_dag(params, emit)
            return
        if job.before:
            emit(f"▶ {job.before()}\n")
        steps = [_as_step(x) for x in job.steps(params)]
        base_env = {**os.environ, "PYTHONUNBUFFERED": "1", "REDIS_URL": _local(), "DATA_DIR": str(settings.data_dir)}
        warnings: list[str] = []
        for i, st in enumerate(steps, 1):
            emit(f"\n▶ [{i}/{len(steps)}] {st.label}\n")
            code = _run_step(st, emit, base_env)
            if code in st.stop_on:
                emit(f"\n■ {st.stop_on[code]}\n")
                code = 0
                break
            if code == 0 or code in st.ok_codes:
                code = 0
                continue
            # pull_upstash exits 10 for "already seeded" — not a failure.
            if job.key == "pull-upstash" and code == 10:
                code = 0
                continue
            if st.allow_fail:
                warnings.append(f"{st.label} (exit {code})")
                emit("  ↳ continuing without it\n")
                code = 0
                continue
            status = "failed"
            break
        if status == "succeeded" and warnings:
            status = "partial"
            emit("\n⚠ Finished with skipped steps:\n" + "".join(f"  - {w}\n" for w in warnings))
        if status in ("succeeded", "partial") and job.after:
            emit(f"\n▶ {job.after()}\n")
    except Exception as exc:
        status, code = "failed", code or 1
        emit(f"\nERROR: {exc}\n")
    finally:
        if job.invalidates:
            data.invalidate()
        with SessionLocal() as db:
            run = db.get(JobRun, run_id)
            run.status, run.exit_code, run.finished_at = status, code, utcnow()
            run.log = "".join(buf)[-200_000:]
            db.commit()
        with _running_lock:
            _running.pop(job.key, None)
        # keep the buffer briefly for late SSE readers
        threading.Timer(120, lambda: _live_logs.pop(run_id, None)).start()
