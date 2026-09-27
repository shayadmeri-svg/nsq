"""EU GMP certificates and non-compliance statements for Indian sites (EudraGMDP).

EudraGMDP is the EU's public database of GMP inspections. For every Indian site an
EU / EEA authority has inspected it holds the certificate (or statement of
non-compliance), and Part 2 of each lists the approved operations in the Union's coded
format, for example:

    1.1.1.2  Aseptically prepared lyophilisates
    1.2.1.13 Tablets
    1.6.1    Microbiological: sterility
    3.1.3    Salt formation / purification (APIs, with the substances named)

This is plant-level, regulator-stated capability data. Statements of non-compliance
add the inspectors' summary of what failed (Part 3).

The site is a stateful Struts application: a search is a form POST that fills the
session, pages are GET ?action=Page&param=N (0-based), and a certificate opens with
?action=Drilldown&param=<id> only while its results page is the current one.

Incremental: a document already parsed in the previous output is not fetched again.
EudraGMDP answers from cloud networks less reliably than from a laptop; run it where
it works and copy data/sources/eudragmdp.json to the server.

    python redis-loader/fetch_source.py eudragmdp
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import urlencode

from .common import Ctx, Unreachable, now_iso, read_normalized, write_normalized

BASE = "https://eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPCompliance.do"
BACK = "https://eudragmdp.ema.europa.eu/inspections/gmpc/prepReviewSubmittedGMPC.do"
INDIA = "c=in,dc=countries,dc=ecd,dc=emea,dc=eu,dc=int"
META = {
    "title": "EudraGMDP — EU GMP certificates (India)",
    "publisher": "European Medicines Agency / EEA national competent authorities",
    "url": BASE,
    "page": "https://eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPCompliance.do",
    "cadence": "weekly (certificates and non-compliance statements are added as inspections close)",
    "feeds": ["Plant registry (EU GMP)", "Stated plant capabilities", "EU non-compliance"],
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- HTML -> lines

class _Text(HTMLParser):
    BLOCK = {"p", "div", "tr", "li", "br", "table", "th", "h1", "h2", "h3", "ol", "ul"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_lines(html: str) -> list[str]:
    p = _Text()
    p.feed(html)
    text = "".join(p.parts).replace("\xa0", " ")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


# --------------------------------------------------------------------------- certificate

_CODE = re.compile(r"^(\d(?:\.\d{1,2}){0,3})\.?\s+(.+)$")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _after(lines: list[str], label: str) -> Optional[str]:
    for i, ln in enumerate(lines):
        if ln.lower().startswith(label.lower()):
            rest = ln[len(label):].strip(" :")
            if rest:
                return rest
            return lines[i + 1] if i + 1 < len(lines) else None
    return None


def parse_certificate(html: str) -> dict[str, Any]:
    """One EudraGMDP certificate / non-compliance statement -> structured record."""
    lines = html_lines(html)
    joined = "\n".join(lines)
    ncr = "NON-COMPLIANCE" in joined.upper() and "STATEMENT OF NON" in joined.upper()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(("CERTIFICATE NUMBER", "Report No"))), 0)
    authority = lines[start - 1] if start > 0 else None
    number = _after(lines, "CERTIFICATE NUMBER") or _after(lines, "Report No")
    manufacturer = _after(lines, "The manufacturer:")
    address = _after(lines, "Site address:")
    oms = re.search(r"(ORG-\d+)\s*/\s*(LOC-\d+)", joined)
    duns = re.search(r"DUNS Number:\s*([\d-]{9,12})", joined)
    insp = re.search(r"latest of which was conducted on\s*(\d{4}-\d{2}-\d{2})", joined)
    basis = re.search(r"Art\.\s*\d+\(\d+\)\s*of (?:Directive|Regulation)[^\n]{0,40}", joined)
    role = ("active_substance" if "active substance manufacturer" in joined.lower()
            else "third_country_ma" if "marketing authorisation(s) listing manufacturers" in joined.lower()
            else "manufacturer")

    # Part 2: coded scope lines (and 'Active Substance:' separators for APIs)
    try:
        p2 = next(i for i, ln in enumerate(lines) if ln == "Part 2")
    except StopIteration:
        p2 = len(lines)
    end = next((i for i in range(p2, len(lines)) if lines[i].startswith(("Clarifying remarks", "Part 3")) or "Name and signature" in lines[i]), len(lines))
    scope: list[dict[str, Any]] = []
    substances: list[str] = []
    products: list[str] = []
    current_substance = None
    product_type = None
    for ln in lines[p2 + 1:end]:
        if ln in ("Human Medicinal Products", "Veterinary Medicinal Products", "Investigational Medicinal Products"):
            product_type = ln.split()[0].lower()
            continue
        m = re.match(r"^\[[\d-]+\](.+?)\(\w{2}\)$", ln)
        if m:
            substances.append(m.group(1).strip())
            continue
        if ln.startswith("Active Substance:"):
            current_substance = ln.split(":", 1)[1].strip()
            continue
        m = _CODE.match(ln)
        if m and not re.match(r"^(NON-COMPLIANT\s+)?(MANUFACTURING OPERATIONS|IMPORTATION)", m.group(2).strip(), re.I):
            code, label = m.group(1), m.group(2).strip()
            detail = None
            label = re.sub(r"\((en|[a-z]{2})\)$", "", label).strip()  # "Dry powder Injection(en)"
            if re.search(r"(steps|substance|Other|Other solid dosage forms|Other non-sterile medicinal products|Culture|Fermentation|source)\s*:", label, re.I):
                label, detail = [x.strip() for x in label.split(":", 1)]  # "3.5.1 Physical processing steps: Drying, Milling"
            scope.append({"code": code, "label": label, "detail": detail or None, "substance": current_substance})
            continue
        if scope and not _CODE.match(ln) and not ln.isupper() and len(ln) < 300 and scope[-1]["detail"] is None \
                and ln.endswith(tuple("abcdefghijklmnopqrstuvwxyz ")) and scope[-1]["label"].endswith("steps"):
            scope[-1]["detail"] = ln
    # dedupe (the same code repeats per substance)
    seen = set()
    uniq = []
    for s in scope:
        k = (s["code"], s["label"], s["detail"], s["substance"])
        if k not in seen:
            seen.add(k)
            uniq.append(s)

    remarks = None
    for i, ln in enumerate(lines):
        if ln.startswith("Clarifying remarks"):
            nxt = [x for x in lines[i + 1:i + 4] if "Name and signature" not in x and not _DATE.fullmatch(x)]
            remarks = nxt[0] if nxt else None
    nature = re.search(r"Nature of non-compliance:\s*(.+?)(?=\n(?:Action taken|Additional comments)|\Z)", joined, re.S)
    action = re.search(r"Action taken/proposed by the NCA:\s*(.+?)(?=\nAdditional comments|\Z)", joined, re.S)
    comments = re.search(r"Additional comments:\s*(.+?)(?=\n\d{4}-\d{2}-\d{2}\n|\nName and signature|\Z)", joined, re.S)
    sig = next((i for i, ln in enumerate(lines) if "Name and signature" in ln), None)
    issued = None
    if sig is not None:
        for ln in reversed(lines[max(0, sig - 3):sig + 1]):
            d = _DATE.search(ln)
            if d:
                issued = d.group(1)
                break
    clean = lambda s: re.sub(r"\s+", " ", s).strip() if s else None  # noqa: E731
    return {
        "type": "NCR" if ncr else "GMPC",
        "number": number,
        "authority": authority,
        "manufacturer": manufacturer,
        "address": address,
        "oms_org": oms.group(1) if oms else None,
        "oms_loc": oms.group(2) if oms else None,
        "duns": duns.group(1) if duns else None,
        "inspection_date": insp.group(1) if insp else None,
        "issued": issued,
        "legal_basis": clean(basis.group(0)) if basis else None,
        "role": role,
        "product_type": product_type,
        "scope": uniq,
        "substances": substances or sorted({s["substance"] for s in uniq if s["substance"]}),
        "products": products,
        "remarks": remarks,
        "ncr": {"nature": clean(nature.group(1)) if nature else None, "action": clean(action.group(1)) if action else None,
                "comments": clean(comments.group(1)) if comments else None} if ncr else None,
    }


# --------------------------------------------------------------------------- search list

class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None
        self._id: Optional[str] = None
        self.total: Optional[int] = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row, self._id = [], None
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "a" and "action=Drilldown" in (a.get("href") or ""):
            # the parser turns "&param" into "¶m" (HTML entity &para;), so read the trailing number
            m = re.search(r"(\d+)\s*$", a["href"])
            self._id = m.group(1) if m else None

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._id and len(self._row) >= 12:
                r = self._row
                self.rows.append({"id": self._id, "number": r[0], "doc_ref": r[1], "type": r[2], "mia": r[3] or None,
                                  "oms_org": r[4] or None, "oms_loc": r[5] or None, "site_name": r[6], "address": r[7],
                                  "city": r[8], "postcode": r[9], "country": r[10], "inspection_date": r[11]})
            self._row, self._id = None, None

    def handle_data(self, data):
        self._text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def close(self):
        super().close()
        m = re.search(r"\d+\s+to\s+\d+\s+of\s+(\d+)", " ".join(self._text))
        self.total = int(m.group(1)) if m else None


def parse_list(html: str) -> tuple[list[dict[str, Any]], Optional[int]]:
    p = _Rows()
    p.feed(html)
    p.close()
    return p.rows, p.total


class _Form(HTMLParser):
    """All fields of the search form with their default values (Struts wants every field)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: list[tuple[str, str]] = []
        self._select: Optional[str] = None
        self._first: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        name = a.get("name")
        if tag == "input" and name:
            t = (a.get("type") or "text").lower()
            if t in ("text", "hidden") or (t == "checkbox" and "checked" in a):
                self.fields.append((name, a.get("value") or ("on" if t == "checkbox" else "")))
        elif tag == "select" and name and "multiple" not in a:
            self._select, self._first = name, None
        elif tag == "option" and self._select is not None:
            if self._first is None or "selected" in a:
                self._first = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "select" and self._select is not None:
            self.fields.append((self._select, self._first or ""))
            self._select = None


# --------------------------------------------------------------------------- crawl

class Session:
    """Cookie-keeping HTTP session on the standard library (the search lives in the server session)."""

    def __init__(self, ctx: Ctx, sleep: float):
        import http.cookiejar
        import urllib.request

        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en"}
        self.ctx = ctx
        self.sleep = sleep

    def _req(self, method: str, url: str, data: Optional[dict] = None) -> str:
        import urllib.error
        import urllib.request

        body = urlencode(data).encode() if data is not None else None
        headers = dict(self.headers, **({"Content-Type": "application/x-www-form-urlencoded"} if body else {}))
        last: Exception | None = None
        for attempt in range(3):
            try:
                with self.opener.open(urllib.request.Request(url, data=body, headers=headers, method=method), timeout=90) as r:
                    text = r.read().decode("utf-8", errors="replace")
                time.sleep(self.sleep)
                return text
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code < 500 and exc.code not in (403, 429):
                    raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
            time.sleep(3 * (attempt + 1))
        raise Unreachable(f"{url}: {last}")

    def search(self, country: str = INDIA) -> tuple[list[dict[str, Any]], int]:
        form = _Form()
        form.feed(self._req("GET", BASE))
        fields = dict(form.fields)
        fields.update({"formid": "frmGMPCSearch", "country": country, "includeNcr": "on", "btnSearchGMPC": "clicked", "isReset": "true"})
        rows, total = parse_list(self._req("POST", BASE, data=fields))
        if total is None:
            raise Unreachable("EudraGMDP search returned no result list (form changed?)")
        return rows, total

    def back_to_list(self) -> None:
        """The detail view's 'Back To Search' button: without it the next page request returns an empty shell."""
        self._req("POST", BACK, data={"btnBackToList": "clicked", "fromwhere": ""})

    def page(self, n: int) -> list[dict[str, Any]]:
        return parse_list(self._req("GET", f"{BASE}?{urlencode({'ctrl': 'searchGMPCResultControlList', 'action': 'Page', 'param': n})}"))[0]

    def detail(self, doc_id: str) -> str:
        return self._req("GET", f"{BASE}?{urlencode({'ctrl': 'searchGMPCResultControlList', 'action': 'Drilldown', 'param': doc_id})}")


def site_key(r: dict[str, Any]) -> str:
    if r.get("oms_loc"):
        return r["oms_loc"]
    return re.sub(r"[^a-z0-9]+", "-", f"{r.get('site_name') or r.get('manufacturer') or ''}-{r.get('postcode') or ''}".lower()).strip("-")


def build_sites(docs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Certificates grouped per site (OMS location), newest first, with the site's current EU status."""
    sites: dict[str, dict[str, Any]] = {}
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in docs.values():
        by[site_key(d)].append(d)
    for k, ds in by.items():
        ds.sort(key=lambda d: (d.get("inspection_date") or "", d.get("issued") or ""), reverse=True)
        head = ds[0]
        gmpc = [d for d in ds if d["type"] == "GMPC"]
        ncr = [d for d in ds if d["type"] == "NCR"]
        last_gmpc = gmpc[0]["inspection_date"] if gmpc else None
        last_ncr = ncr[0]["inspection_date"] if ncr else None
        status = "non_compliant" if last_ncr and (not last_gmpc or last_ncr >= last_gmpc) else ("compliant" if gmpc else "unknown")
        codes: dict[str, dict[str, Any]] = {}
        for d in gmpc:
            for s in d.get("scope") or []:
                c = codes.setdefault(s["code"], {"code": s["code"], "label": s["label"], "details": set(), "last": d.get("inspection_date"),
                                                 "certificates": []})
                if s.get("detail"):
                    c["details"].add(s["detail"])
                if d.get("number") not in c["certificates"]:
                    c["certificates"].append(d.get("number"))
        sites[k] = {
            "key": k, "name": head.get("site_name") or head.get("manufacturer"), "manufacturer": head.get("manufacturer"),
            "address": head.get("address") or head.get("list_address"), "city": head.get("city"), "postcode": head.get("postcode"),
            "oms_org": head.get("oms_org"), "oms_loc": head.get("oms_loc"), "duns": next((d["duns"] for d in ds if d.get("duns")), None),
            "status": status, "last_gmp_inspection": last_gmpc, "last_ncr": last_ncr,
            "roles": sorted({d["role"] for d in ds if d.get("role")}),
            "scope": sorted(({**c, "details": sorted(c["details"])} for c in codes.values()), key=lambda c: [int(x) for x in c["code"].split(".")]),
            "substances": sorted({s for d in gmpc for s in d.get("substances") or []}),
            "documents": [{k2: d.get(k2) for k2 in ("id", "type", "number", "authority", "inspection_date", "issued", "legal_basis", "remarks", "ncr")}
                          | {"scope": [s["code"] for s in d.get("scope") or []]} for d in ds],
        }
    return sites


def run(ctx: Ctx) -> int:
    prev = read_normalized(ctx.name) or {}
    prev_docs: dict[str, dict[str, Any]] = (prev.get("documents") or {})
    sess = Session(ctx, float(ctx.options.get("sleep", 0.6)))
    rows, total = sess.search()
    pages = (total + 9) // 10
    ctx.log(f"  EudraGMDP: {total} certificates / statements for India on {pages} pages")
    docs: dict[str, dict[str, Any]] = {}
    fetched = reused = 0
    limit = ctx.limit or 10 ** 9
    drilled = False  # a detail view is open: go 'Back To Search' before the next page
    empty_pages: list[int] = []
    for n in range(pages):
        if n:
            if drilled:
                sess.back_to_list()
                drilled = False
            rows = sess.page(n)
            if not rows:  # session lost its list: search again, then ask for the page
                sess.search()
                rows = sess.page(n)
            if not rows:
                empty_pages.append(n)
                ctx.log(f"    page {n + 1}: no rows")
                continue
        for r in rows:
            old = prev_docs.get(r["id"])
            if old and old.get("scope") is not None and not ctx.force:
                docs[r["id"]] = {**old, **r}
                reused += 1
                continue
            if fetched >= limit:
                continue
            try:
                html = sess.detail(r["id"])
                drilled = True
                parsed = parse_certificate(html)
            except Unreachable:
                raise
            except Exception as exc:  # a malformed page must not stop the crawl
                ctx.log(f"    {r['id']} {r['site_name']}: {exc}")
                continue
            if not parsed.get("number"):
                ctx.log(f"    {r['id']} {r['site_name']}: detail page did not load")
                continue
            docs[r["id"]] = {**parsed, **{k: v for k, v in r.items() if k not in ("address",)}, "list_address": r["address"],
                             "fetched_at": now_iso()}
            fetched += 1
        if n % 10 == 0:
            ctx.log(f"  page {n + 1}/{pages}: {len(docs)} documents ({fetched} fetched, {reused} unchanged)")
    # keep documents seen before but not listed this time (a lost page must not drop them)
    for k, v in prev_docs.items():
        docs.setdefault(k, v)
    if len(docs) < 0.9 * total:
        ctx.log(f"  WARNING: only {len(docs)} of {total} documents — {len(empty_pages)} pages came back empty; run again to fill in")
    sites = build_sites(docs)
    ncr = sum(1 for s in sites.values() if s["status"] == "non_compliant")
    ctx.log(f"  {len(docs)} documents → {len(sites)} sites · {ncr} currently under an EU non-compliance statement")
    write_normalized(ctx, META, sites, len(sites), extra={"documents": docs, "total_listed": total, "complete": len(docs) >= 0.9 * total,
                                                          "empty_pages": empty_pages})
    return len(sites)
