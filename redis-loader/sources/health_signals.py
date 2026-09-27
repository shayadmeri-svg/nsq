"""Regional health and trade signals for the Playground's "Health & trade" tab.

* nfhs      National Family Health Survey district / state fact-sheet indicators
            (NFHS-4, -5, -6): high blood sugar, raised blood pressure, obesity, anaemia,
            child diarrhoea / ARI, tobacco — the burden behind chronic and anti-infective demand.
            Without a file it downloads open CSV extracts of the official NFHS-5 fact sheets
            (districts, states, India, each with NFHS-4 alongside). A file or folder adds rounds:
            the data.gov.in NFHS-5 district CSV (wide) or a long table
            (Indicator | Geography | Geo Level | Round | Value | Parent State), e.g. NFHS-6.
* idsp      IDSP weekly outbreak reports (PDF tables): state, district, disease, cases, deaths,
            dates, status. Latest N weeks from the IDSP site, or a folder of PDFs.
* comtrade  UN Comtrade: India's exports and imports of pharmaceutical HS codes by partner and
            year (finished dosage forms, bulk, vaccines, antibiotics, hormones, vitamins, APIs).
            COMTRADE_KEY (free subscription) uses the full API; without it the public preview
            endpoint (≤ 500 rows per call) is used.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

from .common import Ctx, NotFound, Unreachable, download, http_get, page_links, read_normalized, write_normalized

# ============================================================================ NFHS

NFHS = {
    "title": "NFHS district fact sheets",
    "publisher": "Ministry of Health & Family Welfare / IIPS (National Family Health Survey)",
    "url": "https://github.com/jvargh7/nfhs5_factsheets",
    "page": "https://www.nfhsiips.in/nfhsuser/release-details.php",
    "cadence": "per survey round (NFHS-5 2019–21, NFHS-6 2023–24)",
    "feeds": ["Health & trade · disease burden by district", "Chronic-disease prevalence"],
}

# key -> (label, group, regex on the indicator text (lower-cased), unit)
INDICATORS: dict[str, tuple[str, str, str]] = {
    "sugar_women": ("Women 15+: high blood sugar or on medicine", "Diabetes",
                    r"women.*blood sugar.*(taking medicine|or taking|on medicine)"),
    "sugar_men": ("Men 15+: high blood sugar or on medicine", "Diabetes",
                  r"(?<!wo)men.*blood sugar.*(taking medicine|or taking|on medicine)"),
    "bp_women": ("Women 15+: raised blood pressure or on medicine", "Hypertension",
                 r"women.*(elevated|raised|high).*blood pressure.*(taking medicine|or taking|on medicine)"),
    "bp_men": ("Men 15+: raised blood pressure or on medicine", "Hypertension",
               r"(?<!wo)men.*(elevated|raised|high).*blood pressure.*(taking medicine|or taking|on medicine)"),
    "obese_women": ("Women 15–49: overweight or obese", "Obesity", r"women.*overweight or obese"),
    "obese_men": ("Men 15–49: overweight or obese", "Obesity", r"(?<!wo)men.*overweight or obese"),
    "anaemia_women": ("Women 15–49: anaemic", "Anaemia", r"^all women age 15.?49 years who are anaemic"),
    "anaemia_children": ("Children 6–59 months: anaemic", "Anaemia", r"children age 6.?59 months.*anaemic"),
    "diarrhoea_children": ("Children <5: diarrhoea in the last 2 weeks", "Infections", r"prevalence of diarrh"),
    "ari_children": ("Children <5: acute respiratory infection symptoms", "Infections", r"prevalence of symptoms of acute respiratory|^prevalence of ari"),
    "tobacco_men": ("Men 15+: use any tobacco", "Risk factors", r"(?<!wo)men age 15 years and above who use any kind of tobacco"),
}
_ROUND = re.compile(r"nfhs[\s_-]*([456])", re.I)


def _indicator_key(text: str) -> Optional[str]:
    t = re.sub(r"^\d+\.\s*", "", re.sub(r"\s+", " ", (text or "").lower()).strip())  # fact-sheet row numbers
    for k, (_l, _g, rx) in INDICATORS.items():
        if re.search(rx, t):
            return k
    return None


def _num(v: Any) -> Optional[float]:
    s = str(v if v is not None else "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m or s.lower() in ("na", "n/a", "*", "-"):
        return None
    return float(m.group(0))


def _rows_of(path: Path) -> list[list[Any]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    delim = max((",", "\t", ";"), key=text[:5000].count)
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _k(h: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


_STATES = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
           "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir",
           "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
           "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
           "Uttar Pradesh", "Uttarakhand", "West Bengal"]
_STATE_KEY = {re.sub(r"and|[^a-z]", "", s.lower()): s for s in _STATES} | {"nctdelhi": "Delhi", "nctofdelhi": "Delhi", "orissa": "Odisha",
                                                                            "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand"}


def canon_state(name: Any) -> Optional[str]:
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    if not s:
        return None
    if s.lower() in ("india", "all india"):
        return "India"
    return _STATE_KEY.get(re.sub(r"and|[^a-z]", "", s.lower()), s)


# The fact sheets list women's rows before men's under section headings, so the row text often lacks
# "women" / "men": the n-th occurrence of these indicators within one geography is women (1st) or men (2nd).
_PAIRED = {"sugar": r"blood sugar.*(taking medicine|or taking)", "bp": r"elevated blood pressure.*(taking medicine|or taking)"}


def _key_in_context(text: str, seen: dict[str, int]) -> Optional[str]:
    t = re.sub(r"\s+", " ", (text or "").lower())
    key = _indicator_key(t)
    if key and not key.startswith(("sugar", "bp")):
        return key
    for base, rx in _PAIRED.items():
        if re.search(rx, t):
            if re.search(r"\bwomen\b", t):
                return f"{base}_women"
            if re.search(r"(?<!wo)\bmen\b", t):
                return f"{base}_men"
            seen[base] = seen.get(base, 0) + 1
            return f"{base}_women" if seen[base] == 1 else f"{base}_men" if seen[base] == 2 else None
    return key


def parse_nfhs(path: Path, default_round: Optional[str] = None) -> list[dict[str, Any]]:
    """Normalised rows {level, state, district, round, ind, value} from one NFHS table.

    Layouts handled: long with one value column per round (State, District, Indicator, NFHS-5, NFHS-4 — the
    pratapvardhan / jvargh7 fact-sheet extracts), long with Round + Value columns (Indicator | Geography | Geo Level
    | Round | Value | Parent State), and wide (one row per district, one column per indicator — data.gov.in).
    """
    rows = [r for r in _rows_of(path) if any(str(c or "").strip() for c in r)]
    if not rows:
        return []
    head = [_k(c) for c in rows[0]]
    rnd_file = _ROUND.search(path.name)
    rnd_default = default_round or (f"NFHS-{rnd_file.group(1)}" if rnd_file else "NFHS-5")
    ix = {h: i for i, h in enumerate(head)}
    out: list[dict[str, Any]] = []

    def val(r: list[Any], i: Optional[int]) -> Any:
        return r[i] if i is not None and i < len(r) else None

    if "indicator" in ix:
        ii = ix["indicator"]
        di = next((ix[h] for h in ("district", "districtname", "districtnames") if h in ix), None)
        si = next((ix[h] for h in ("state", "statename", "stateut", "parentstate") if h in ix), None)
        gi = ix.get("geography")
        li = ix.get("geolevel")
        ri, vi = ix.get("round"), ix.get("value")
        # value columns: one per round ("NFHS-5", "NFHS5", "nfhs5_total", "Total" = the file's round)
        vcols = []
        for i, h in enumerate(head):
            if h.startswith("flag") or h.endswith("note") or "urban" in h or "rural" in h:
                continue
            m = re.fullmatch(r"nfhs([456])(total)?", h)
            if m:
                vcols.append((i, f"NFHS-{m.group(1)}"))
            elif h == "total":
                vcols.append((i, rnd_default))
        seen: dict[tuple, dict[str, int]] = {}
        for r in rows[1:]:
            text = str(val(r, ii) or "")
            if gi is not None:  # Indicator | Geography | Geo Level | Round | Value | Parent State
                level = str(val(r, li) or "district").strip().lower()
                level = "india" if level in ("national", "india", "country") else "state" if level.startswith("state") else "district"
                geo = str(val(r, gi) or "").strip()
                state = canon_state(val(r, ix.get("parentstate")) or (geo if level != "district" else None))
                district = geo if level == "district" else None
            else:
                district = str(val(r, di) or "").strip() or None if di is not None else None
                state = canon_state(val(r, si))
                level = "district" if district else ("india" if state == "India" else "state")
            ctx = seen.setdefault((level, state, district, str(val(r, ri) or "")), {})
            key = _key_in_context(text, ctx)
            if not key:
                continue
            pairs = [(val(r, vi), (lambda m: f"NFHS-{m.group(1)}" if m else rnd_default)(_ROUND.search(str(val(r, ri) or ""))))] \
                if vi is not None else [(val(r, i), rnd) for i, rnd in vcols]
            for raw, rnd in pairs:
                v = _num(raw)
                if v is not None:
                    out.append({"level": level, "state": state if level != "india" else "India", "district": district,
                                "round": rnd, "ind": key, "value": v})
        return out
    # wide table: one row per district / state, one column per indicator
    di = next((i for i, h in enumerate(head) if h in ("districtnames", "districtname", "district", "districts")), None)
    si = next((i for i, h in enumerate(head) if h in ("stateut", "statesuts", "state", "statename", "stateunionterritory", "statesut")), None)
    if si is None and di is None:
        raise ValueError(f"{path.name}: neither an indicator table nor district/state columns; header starts {rows[0][:6]}")
    cols, seen_w = [], {}
    for i, h in enumerate(rows[0]):
        if i in (di, si):
            continue
        key = _key_in_context(str(h or ""), seen_w)
        if key:
            m = _ROUND.search(str(h))
            cols.append((i, key, f"NFHS-{m.group(1)}" if m else rnd_default))
    for r in rows[1:]:
        dist = str(r[di]).strip() if di is not None and di < len(r) and r[di] else None
        st = canon_state(r[si]) if si is not None and si < len(r) and r[si] else None
        if not (dist or st):
            continue
        level = "district" if dist else ("india" if st == "India" else "state")
        for i, key, rnd in cols:
            v = _num(r[i]) if i < len(r) else None
            if v is not None:
                out.append({"level": level, "state": st, "district": dist, "round": rnd, "ind": key, "value": v})
    return out


# Open extracts of the official NFHS-5 fact sheets (rchiips.org), used when no file is given:
# jvargh7/nfhs5_factsheets (MIT) — all ~705 districts, states and India, each with the NFHS-4 value alongside.
NFHS_DEFAULT = [
    "https://raw.githubusercontent.com/jvargh7/nfhs5_factsheets/main/data%20for%20analysis/districts.csv",
    "https://raw.githubusercontent.com/jvargh7/nfhs5_factsheets/main/data%20for%20analysis/states.csv",
    "https://raw.githubusercontent.com/jvargh7/nfhs5_factsheets/main/data%20for%20analysis/india.csv",
]


def run_nfhs(ctx: Ctx) -> int:
    if ctx.from_file:
        files = sorted(p for p in ([ctx.from_file] if ctx.from_file.is_file() else ctx.from_file.iterdir())
                       if p.suffix.lower() in (".csv", ".xlsx", ".tsv", ".txt"))
    else:
        files = [download(ctx, u, "nfhs5_" + u.rsplit("/", 1)[-1]) for u in NFHS_DEFAULT]
    prev = read_normalized(ctx.name) or {}
    rows: list[dict[str, Any]] = []
    for f in files:
        got = parse_nfhs(f, ctx.options.get("round"))
        ctx.log(f"  {f.name}: {len(got):,} values")
        rows += got
    # keep rounds the new files don't cover (e.g. load NFHS-6 later without losing NFHS-5)
    new_rounds = {r["round"] for r in rows}
    rows += [r for r in (prev.get("data") or []) if r.get("round") not in new_rounds]
    if not rows:
        raise NotFound("no NFHS indicator recognised in the file(s)")
    seen, uniq = set(), []
    for r in rows:
        k = (r["level"], r.get("state"), r.get("district"), r["round"], r["ind"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    rounds = sorted({r["round"] for r in uniq})
    ctx.log(f"  {len(uniq):,} values · rounds {rounds} · {len({(r.get('state'), r.get('district')) for r in uniq if r['level'] == 'district'}):,} districts")
    write_normalized(ctx, NFHS, uniq, len(uniq), extra={"indicators": {k: {"label": v[0], "group": v[1]} for k, v in INDICATORS.items()},
                                                          "rounds": rounds})
    return len(uniq)


# ============================================================================ IDSP

IDSP_PAGE = "https://idsp.mohfw.gov.in/index4.php?lang=1&level=0&linkid=406&lid=3689"
IDSP = {
    "title": "IDSP weekly outbreaks",
    "publisher": "Integrated Disease Surveillance Programme, MoHFW",
    "url": IDSP_PAGE,
    "page": IDSP_PAGE,
    "cadence": "weekly PDFs; latest 26 weeks kept",
    "feeds": ["Health & trade · outbreaks by district", "Anti-infective demand signals"],
}

# canonical disease -> (regex, medicines whose demand it drives — tracked molecule keys when they exist)
DISEASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Acute diarrhoeal disease": (r"acute diarr|a\.?d\.?d\b|gastro", ("oral rehydration salts", "zinc", "ofloxacin", "metronidazole")),
    "Food poisoning": (r"food poison", ("oral rehydration salts", "ondansetron")),
    "Cholera": (r"cholera", ("oral rehydration salts", "doxycycline", "azithromycin")),
    "Typhoid": (r"typhoid|enteric fever", ("azithromycin", "ceftriaxone", "cefixime")),
    "Hepatitis A / E": (r"hepatitis|jaundice", ()),
    "Dengue": (r"dengue", ("paracetamol",)),
    "Chikungunya": (r"chikungunya", ("paracetamol",)),
    "Malaria": (r"malaria", ("artemether", "artesunate", "chloroquine", "primaquine")),
    "Leptospirosis": (r"leptospir", ("doxycycline", "ceftriaxone")),
    "Scrub typhus": (r"scrub typhus|rickettsi", ("doxycycline", "azithromycin")),
    "Japanese encephalitis / AES": (r"japanese enceph|\baes\b|acute enceph", ()),
    "Measles": (r"measles", ("vitamin a",)),
    "Chickenpox": (r"chicken ?pox|varicella", ("acyclovir",)),
    "Mumps": (r"mumps", ()),
    "Diphtheria": (r"diphtheria", ("penicillin", "erythromycin")),
    "Influenza / ILI": (r"influenza|h1n1|\bili\b|swine flu", ("oseltamivir",)),
    "Fever (unknown)": (r"fever", ("paracetamol",)),
}
_HEAD = {"state": ("nameofstateut", "state", "stateut", "nameofstate"), "district": ("nameofdistrict", "district"),
         "disease": ("diseaseillness", "disease", "illness"), "cases": ("noofcases", "cases"), "deaths": ("noofdeaths", "deaths"),
         "start": ("dateofstartofoutbreak", "dateofstart", "startdate"), "reported": ("dateofreporting", "reportingdate"),
         "status": ("currentstatus", "status"), "id": ("uniqueid", "id")}


def disease_key(text: str) -> str:
    t = (text or "").lower()
    for k, (rx, _m) in DISEASES.items():
        if re.search(rx, t):
            return k
    return "Other"


def _d(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
    if not m:
        return None
    y = int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return date(y, int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def parse_idsp_tables(tables: Iterable[list[list[Any]]], week: Optional[str] = None) -> list[dict[str, Any]]:
    """Outbreak rows from the tables of one weekly report. Wrapped cells (continuation rows) are merged upward."""
    out: list[dict[str, Any]] = []
    cols: Optional[dict[str, int]] = None
    for t in tables:
        for raw in t:
            cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in raw]
            keys = [_k(c) for c in cells]
            found = {f: next((i for i, k in enumerate(keys) if any(k.startswith(n) for n in names)), None) for f, names in _HEAD.items()}
            if found["disease"] is not None and found["district"] is not None and (found["cases"] is not None or found["state"] is not None):
                cols = {k: v for k, v in found.items() if v is not None}
                continue
            if cols is None or not any(cells):
                continue
            get = lambda f: cells[cols[f]] if f in cols and cols[f] < len(cells) else ""  # noqa: E731
            dis, dist = get("disease"), get("district")
            if not dis and not dist and out:  # continuation of the row above
                for f in ("status",):
                    if get(f):
                        out[-1][f] = (out[-1].get(f) or "") + " " + get(f)
                continue
            cases = _num(get("cases"))
            if not dis or cases is None:
                continue
            out.append({"id": get("id") or None, "state": get("state") or (out[-1]["state"] if out else None), "district": dist or None,
                        "disease": dis, "disease_key": disease_key(dis), "cases": int(cases), "deaths": int(_num(get("deaths")) or 0),
                        "start": _d(get("start")), "reported": _d(get("reported")), "status": get("status") or None, "week": week})
    return out


def _week_label(name: str, text: str = "") -> Optional[str]:
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s_-]*week[\s_-]*(?:of[\s_-]*)?(\d{4})", f"{name} {text[:400]}", re.I)
    if m:
        return f"{m.group(2)}-W{int(m.group(1)):02d}"
    m = re.search(r"(\d{4})[\s_-]*w(?:eek)?[\s_-]*(\d{1,2})", name, re.I)
    return f"{m.group(1)}-W{int(m.group(2)):02d}" if m else None


def parse_idsp_pdf(path: Path) -> list[dict[str, Any]]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        first = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
        week = _week_label(path.name, first)
        tables = [t for page in pdf.pages for t in (page.extract_tables() or [])]
    rows = parse_idsp_tables(tables, week)
    for r in rows:
        r["file"] = path.name
    return rows


_A = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def _anchors(html: str, base: str) -> list[tuple[str, str]]:
    from html import unescape
    from urllib.parse import urljoin

    return [(urljoin(base, unescape(h.strip())), re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", t))).strip()) for h, t in _A.findall(html)]


def _get_page(ctx: Ctx, url: str, name: str) -> str:
    try:
        html = http_get(url, timeout=60, retries=1).decode("utf-8", errors="replace")
    except Exception as exc:
        raise Unreachable(f"IDSP page {url}: {exc}") from exc
    (ctx.raw_dir / name).write_text(html, encoding="utf-8")
    return html


def idsp_pdf_links(ctx: Ctx) -> list[tuple[str, str]]:
    """Weekly-report PDFs on the IDSP outbreaks page, newest first. The PDFs are often served under numeric
    names (WriteReadData/...), so the link text ("31st week 2026") matters more than the URL. When the page
    only lists years, the newest year pages are followed."""
    html = _get_page(ctx, IDSP_PAGE, "page.html")
    anchors = _anchors(html, IDSP_PAGE)
    pdfs = [(u, t) for u, t in anchors if re.search(r"\.pdf(\?|$)", u, re.I)]
    if not pdfs:
        years = sorted({(int(m.group(0)), u) for u, t in anchors if (m := re.fullmatch(r"20\d\d", t.strip()))}, reverse=True)
        for i, (_y, u) in enumerate(years[:2]):
            pdfs += [(pu, pt) for pu, pt in _anchors(_get_page(ctx, u, f"page_{_y}.html"), u) if re.search(r"\.pdf(\?|$)", pu, re.I)]
    weekly = [(u, t) for u, t in pdfs if re.search(r"week|wk|outbreak", f"{u} {t}", re.I)] or pdfs

    def order(ut: tuple[str, str]) -> tuple[int, int]:
        lab = _week_label(ut[1] + " " + ut[0])
        return (int(lab[:4]), int(lab[-2:])) if lab else (0, 0)

    weekly.sort(key=order, reverse=True)
    seen, out = set(), []
    for u, t in weekly:
        if u not in seen:
            seen.add(u)
            out.append((u, _week_label(t + " " + u) or ""))
    return out


def run_idsp(ctx: Ctx) -> int:
    prev = read_normalized(ctx.name) or {}
    keep = int(ctx.limit or ctx.options.get("weeks") or 26)
    if ctx.from_file:
        pdfs = [ctx.from_file] if ctx.from_file.is_file() else sorted(ctx.from_file.glob("*.pdf"))
    else:
        links = idsp_pdf_links(ctx)
        if not links:
            raise NotFound(f"no PDF links found on the IDSP outbreaks page — the page was saved to {ctx.raw_dir / 'page.html'}; "
                           "download a few weekly PDFs in a browser and run with a folder instead")
        ctx.log(f"  {len(links)} weekly reports listed; fetching the latest {min(keep, len(links))}")
        pdfs = []
        for u, label in links[:keep]:
            # keep the week (from the link text) in the file name: the PDFs are often served under numeric names
            name = (f"{label}_" if label else "") + re.sub(r"[^A-Za-z0-9._-]+", "_", u.rsplit("/", 1)[-1])[-100:]
            try:
                pdfs.append(download(ctx, u, name))
            except Exception as exc:  # one bad week must not stop the rest
                ctx.log(f"  skipped {u}: {exc}")
                p = ctx.raw_dir / name
                if p.exists():
                    pdfs.append(p)
    rows: list[dict[str, Any]] = []
    for p in pdfs:
        try:
            got = parse_idsp_pdf(p)
        except Exception as exc:
            ctx.log(f"  could not read {p.name}: {exc}")
            continue
        ctx.log(f"  {p.name}: {len(got)} outbreaks ({got[0]['week'] if got else 'week ?'})")
        rows += got
    files = {r["file"] for r in rows}
    rows += [r for r in (prev.get("data") or []) if r.get("file") not in files]
    if not rows:
        raise NotFound("no outbreak rows parsed")
    seen, uniq = set(), []
    for r in rows:
        k = r.get("id") or (r.get("state"), r.get("district"), r.get("disease"), r.get("start"))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    weeks = sorted({r["week"] for r in uniq if r.get("week")})
    ctx.log(f"  {len(uniq):,} outbreaks · weeks {weeks[0] if weeks else '?'} … {weeks[-1] if weeks else '?'}")
    write_normalized(ctx, IDSP, uniq, len(uniq), extra={"weeks": weeks,
                                                          "diseases": {k: list(v[1]) for k, v in DISEASES.items()}})
    return len(uniq)


# ============================================================================ UN Comtrade

COMTRADE = {
    "title": "UN Comtrade — India pharma trade",
    "publisher": "United Nations Statistics Division",
    "url": "https://comtradeapi.un.org/data/v1/get/C/A/HS",
    "page": "https://comtradeplus.un.org/",
    "cadence": "annual (a year is complete ~6–12 months after it ends)",
    "feeds": ["Health & trade · exports and imports by partner", "API import dependence"],
}
HS: dict[str, tuple[str, str]] = {
    "3004": ("Medicaments, dosed (finished formulations)", "finished"),
    "3003": ("Medicaments, not dosed (bulk)", "finished"),
    "3002": ("Vaccines, blood products, immunological", "biologic"),
    "3006": ("Pharmaceutical goods (sutures, kits…)", "finished"),
    "2941": ("Antibiotics", "api"),
    "2937": ("Hormones, steroids", "api"),
    "2936": ("Vitamins", "api"),
    "2939": ("Alkaloids", "api"),
    "2933": ("Heterocyclics with nitrogen (many APIs)", "api"),
    "2934": ("Nucleic acids, other heterocyclics", "api"),
    "2935": ("Sulphonamides", "api"),
    "2942": ("Other organic compounds", "api"),
}
INDIA = 699


def _comtrade_call(params: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if key:
        url, headers = COMTRADE["url"], {"Ocp-Apim-Subscription-Key": key}
    else:
        url, headers = "https://comtradeapi.un.org/public/v1/preview/C/A/HS", {}
    raw = http_get(url, params=params, accept="application/json", timeout=90, headers=headers)
    res = json.loads(raw.decode("utf-8"))
    if res.get("error"):
        raise Unreachable(f"Comtrade: {res['error']}")
    return res.get("data") or []


def normalise_comtrade(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if str(r.get("reporterCode")) not in (str(INDIA), "") or r.get("customsCode") not in (None, "C00"):
            continue
        if r.get("motCode") not in (None, 0) or r.get("partner2Code") not in (None, 0):
            continue  # keep the all-modes, no-second-partner totals only
        val = r.get("primaryValue") if r.get("primaryValue") is not None else r.get("cifvalue") or r.get("fobvalue")
        if val is None:
            continue
        out.append({"year": int(r.get("period") or r.get("refYear")), "flow": "export" if str(r.get("flowCode")) == "X" else "import",
                    "hs": str(r.get("cmdCode")), "partner_code": int(r.get("partnerCode") or 0),
                    "partner": r.get("partnerDesc") or str(r.get("partnerCode")), "partner_iso": r.get("partnerISO"),
                    "value_usd": float(val), "net_kg": float(r["netWgt"]) if r.get("netWgt") not in (None, "") else None})
    return out


def run_comtrade(ctx: Ctx) -> int:
    prev = read_normalized(ctx.name) or {}
    key = os.environ.get("COMTRADE_KEY", "")
    if ctx.from_file:
        raw = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        rows = normalise_comtrade(raw.get("data", raw) if isinstance(raw, dict) else raw)
    else:
        last = date.today().year - 1
        years = list(range(last - 5, last + 1))
        rows = []
        for hs in HS:
            for flow in ("X", "M"):
                if key:  # full API: all years in one call
                    got = _comtrade_call({"reporterCode": INDIA, "period": ",".join(map(str, years)), "cmdCode": hs, "flowCode": flow,
                                          "includeDesc": "true"}, key)
                else:  # preview: ≤ 500 rows, so one year per call
                    got = []
                    for y in years:
                        got += _comtrade_call({"reporterCode": INDIA, "period": y, "cmdCode": hs, "flowCode": flow, "includeDesc": "true"}, "")
                        time.sleep(1.1)
                n = normalise_comtrade(got)
                ctx.log(f"  HS {hs} {'exports' if flow == 'X' else 'imports'}: {len(n):,} partner-years")
                rows += n
                time.sleep(0.4 if key else 1.1)
    if not rows:
        if prev.get("data"):
            raise Unreachable("Comtrade returned nothing — keeping the previous file")
        raise NotFound("Comtrade returned no rows")
    years_got = sorted({r["year"] for r in rows})
    ctx.log(f"  {len(rows):,} rows · years {years_got} · {'full API' if key else 'public preview'}")
    write_normalized(ctx, COMTRADE, rows, len(rows), extra={"hs": {k: {"label": v[0], "group": v[1]} for k, v in HS.items()},
                                                             "years": years_got, "mode": "api" if key else "preview"})
    return len(rows)
