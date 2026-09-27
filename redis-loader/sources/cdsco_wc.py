"""CDSCO International Cell: Written Confirmations for API exports to the EU, and the cell's other documents.

The International Cell page (cdsco.gov.in/opencms/opencms/en/International-cell1/) lists every Written
Confirmation (WC) CDSCO has issued since 2013 under EU Directive 2011/62/EU (Article 46b): the letter an
Indian API maker needs to export an active substance to the EU, confirming its site follows EU-equivalent
GMP. About 700 rows: WC number, company, products ("Pregabalin BP/EP and 5 items"), release date and a
PDF (the letter itself: site address, full product list, validity). A few rows are office memoranda.

The page's download links go through a JSP that answers with an <iframe> pointing at the real PDF; the
PDF is resolved once per document and remembered in the output file.

Outputs:
    data/sources/cdsco_wc.json      index: one record per document, plus the cell's functions / delegations
    data/docs/cdsco_wc/<id>.pdf     the PDFs (~1.5 GB for all of them; only new ones are downloaded)

CDSCO refuses cloud networks: run on a laptop (just fetch-cdsco-wc) and push with just push-wc.
    python fetch_source.py cdsco_wc                  # index + every PDF not yet downloaded
    python fetch_source.py cdsco_wc --limit 50       # index + at most 50 new PDFs
    NSQ_WC_PDFS=0 python fetch_source.py cdsco_wc    # index only
    python fetch_source.py cdsco_wc --from-file page.html   # parse a saved copy of the page
"""

from __future__ import annotations

import base64
import html as htmllib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from .common import Ctx, NotFound, data_dir, headers_for, http_get, read_normalized, write_normalized

PAGE = "https://cdsco.gov.in/opencms/opencms/en/International-cell1/"
META = {
    "title": "CDSCO Written Confirmations (API exports to the EU)",
    "publisher": "CDSCO International Cell",
    "url": PAGE,
    "page": PAGE,
    "cadence": "a few new confirmations a week",
    "feeds": ["Playground · Written confirmations"],
}
MAX_PDF = 80 * 1024 * 1024  # one row claims 1.3 GB; nothing real is above ~25 MB

_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_HREF = re.compile(r"""href=['"]([^'"]*download_file_division\.jsp\?num_id=([^'"&]+))['"]""", re.I)
_TAG = re.compile(r"<[^>]+>")


def docs_dir() -> Path:
    p = data_dir() / "docs" / "cdsco_wc"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG.sub(" ", s))).strip()


def _id(num_id: str) -> str:
    try:
        v = base64.b64decode(num_id + "=" * (-len(num_id) % 4)).decode()
        if v.isdigit():
            return v
    except Exception:
        pass
    return re.sub(r"[^A-Za-z0-9]", "", num_id)


def norm_wc(raw: str) -> Optional[str]:
    """'WC -0104' / 'WC/0037' / 'WC-340n' / 'WC-0491A3' -> 'WC-0104' / 'WC-0037' / 'WC-0340' / 'WC-0491'. None for memoranda."""
    m = re.match(r"^\s*WC\s*[-/ ]?\s*0*(\d{1,4})", raw or "", re.I)
    return f"WC-{int(m.group(1)):04d}" if m else None


def _kb(s: str) -> Optional[int]:
    m = re.search(r"([\d,]+)", s or "")
    return int(m.group(1).replace(",", "")) if m else None


def _items(products: str) -> int:
    m = re.search(r"and\s+(\d+)\s+items?", products or "", re.I)
    if m:
        return int(m.group(1)) + 1
    return len([p for p in re.split(r"\s+and\s+|,", products or "") if p.strip()]) if products else 0


def parse_table(page: str) -> list[dict[str, Any]]:
    i = page.find('id="example"')
    body = page[i:page.find("</table>", i)] if i >= 0 else page
    out = []
    for tr in _TR.findall(body):
        tds = _TD.findall(tr)
        if len(tds) < 6:
            continue
        link = _HREF.search(tr)
        if not link:
            continue
        cells = [_text(t) for t in tds]
        raw_wc, company, products, date = cells[1], cells[2], cells[3], cells[4][:10]
        wc = norm_wc(raw_wc)
        out.append({
            "id": _id(link.group(2)),
            "num_id": link.group(2),
            "kind": "wc" if wc else "notice",
            "wc": wc,
            "wc_raw": raw_wc,
            "company": re.sub(r"^M/s\.?\s*", "", company, flags=re.I).strip(" ,") or None,
            "products": products or None,
            "items": _items(products),
            "date": date if re.match(r"\d{4}-\d{2}-\d{2}", date) else None,
            "size_kb": _kb(cells[6] if len(cells) > 6 else ""),
            "download": urljoin(PAGE, htmllib.unescape(link.group(1))),
        })
    # renewals and amendments reuse the WC number: newest first, mark the older ones
    latest: dict[str, str] = {}
    for r in sorted(out, key=lambda r: r["date"] or "", reverse=True):
        if r["wc"]:
            r["latest"] = r["wc"] not in latest
            latest.setdefault(r["wc"], r["id"])
    return out


def parse_about(page: str) -> list[dict[str, Any]]:
    """The cell's tabs (Functions, Foreign Delegates, SOP, Organogram): heading, text paragraphs and PDF links."""
    names = dict(re.findall(r'href="#([^"]+-tab-\d+)"[^>]*>.*?<p>(.*?)</p>', page, re.S))
    out = []
    for pid, title in names.items():
        m = re.search(rf'<div id="{re.escape(pid)}"[^>]*>(.*?)(?=<div id="[^"]+-tab-\d+"|<!--/tab-content-->|<table\b|</section>)', page, re.S)
        if not m:
            continue
        chunk = m.group(1)
        paras = [t for t in (_text(x) for x in re.findall(r"<(?:p|li)\b[^>]*>(.*?)</(?:p|li)>", chunk, re.S)) if t]
        paras = [p for i, p in enumerate(paras) if p not in paras[:i]]
        links = [{"title": _text(t) or u.rsplit("/", 1)[-1], "url": urljoin(PAGE, htmllib.unescape(u))}
                 for u, t in re.findall(r"""<a\b[^>]*href=['"]([^'"]+\.pdf)['"][^>]*>(.*?)</a>""", chunk, re.S | re.I)]
        out.append({"title": _text(title), "paragraphs": paras, "links": links})
    return out


def resolve_pdf(download_url: str) -> Optional[str]:
    """The JSP answers with <iframe src='/opencms/resources/…/X.pdf'>; return that URL (spaces encoded)."""
    body = http_get(download_url, timeout=60, retries=1).decode("utf-8", errors="replace")
    if body.lstrip().startswith("%PDF"):
        return download_url
    m = re.search(r"""src=['"]([^'"]+)['"]""", body)
    if not m:
        return None
    return urljoin(PAGE, quote(htmllib.unescape(m.group(1)), safe="/:?=&%"))


def fetch_pdf(url: str, dest: Path) -> int:
    req = Request(url, headers=headers_for(url) or {})
    tmp = dest.with_suffix(".part")
    n = 0
    with urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
        first = True
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            if first and not chunk.startswith(b"%PDF"):
                raise NotFound(f"not a PDF: {url}")
            first = False
            n += len(chunk)
            if n > MAX_PDF:
                raise NotFound(f"larger than {MAX_PDF >> 20} MB: {url}")
            f.write(chunk)
    os.replace(tmp, dest)
    return n


def pdf_text(path: Path, limit: int = 12000) -> str:
    """Text of the letter (site address, full product list, validity) for search. Scanned letters give ''."""
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        with pdfplumber.open(str(path)) as pdf:
            parts = []
            for page in pdf.pages[:8]:
                parts.append(page.extract_text() or "")
                if sum(map(len, parts)) > limit:
                    break
    except Exception:
        return ""
    return re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()[:limit]


_VALID = re.compile(r"valid\w*\s+(?:up\s*to|upto|till|until)\s*:?\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", re.I)


def valid_until(text: str) -> Optional[str]:
    m = _VALID.search(text or "")
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    y = y + 2000 if y < 100 else y
    return f"{y:04d}-{mo:02d}-{d:02d}" if 1 <= mo <= 12 and 1 <= d <= 31 else None


def run(ctx: Ctx) -> int:
    if ctx.from_file:
        page = ctx.from_file.read_text(encoding="utf-8", errors="replace")
    else:
        page = http_get(PAGE, timeout=120).decode("utf-8", errors="replace")
        (ctx.raw_dir / "page.html").write_text(page, encoding="utf-8")
    rows = parse_table(page)
    if not rows:
        raise NotFound(f"no Written Confirmation rows found on {PAGE} (saved to {ctx.raw_dir / 'page.html'})")
    about = parse_about(page)
    prev = {r["id"]: r for r in ((read_normalized(ctx.name) or {}).get("data") or [])}
    for r in rows:  # carry over what earlier runs learnt (PDF URL, text, validity)
        for k in ("pdf_url", "text", "valid_until", "pages"):
            if prev.get(r["id"], {}).get(k) is not None:
                r[k] = prev[r["id"]][k]
    ctx.log(f"  {len(rows)} documents listed ({sum(r['kind'] == 'wc' for r in rows)} written confirmations)")

    want_pdfs = os.environ.get("NSQ_WC_PDFS", "1") != "0" and not ctx.from_file
    folder = docs_dir()
    if want_pdfs:
        todo = [r for r in rows if not (folder / f"{r['id']}.pdf").exists()]
        if ctx.limit:
            todo = todo[: ctx.limit]
        ctx.log(f"  {len(todo)} PDFs to download ({sum(r['size_kb'] or 0 for r in todo) / 1024:,.0f} MB listed)")

        def one(r: dict[str, Any]) -> tuple[str, Optional[str]]:
            try:
                if not r.get("pdf_url"):
                    r["pdf_url"] = resolve_pdf(r["download"])
                if not r["pdf_url"]:
                    return r["id"], "no PDF behind the link"
                fetch_pdf(r["pdf_url"], folder / f"{r['id']}.pdf")
                return r["id"], None
            except Exception as exc:  # one bad file must not stop the rest
                return r["id"], str(exc)[:200]

        done = failed = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for i, (rid, err) in enumerate(pool.map(one, todo), 1):
                if err:
                    failed += 1
                    ctx.log(f"  skipped {rid}: {err}")
                else:
                    done += 1
                if i % 25 == 0:
                    ctx.log(f"  … {i}/{len(todo)}")
        ctx.log(f"  downloaded {done} PDFs, {failed} failed (re-run to retry)")
        for a in about:  # the organogram etc.
            for ln in a["links"]:
                name = "about-" + re.sub(r"[^A-Za-z0-9._-]+", "_", ln["url"].rsplit("/", 1)[-1])
                ln["file"] = name
                if not (folder / name).exists():
                    try:
                        fetch_pdf(ln["url"], folder / name)
                    except Exception as exc:
                        ctx.log(f"  skipped {ln['url']}: {exc}")

    n_text = 0
    for r in rows:
        p = folder / f"{r['id']}.pdf"
        r["has_pdf"] = p.exists()
        if r["has_pdf"]:
            r["bytes"] = p.stat().st_size
            if r.get("text") is None:
                r["text"] = pdf_text(p)
                r["valid_until"] = valid_until(r["text"])
                n_text += 1
    if n_text:
        ctx.log(f"  read the text of {n_text} new PDFs ({sum(1 for r in rows if r.get('text'))} of {sum(r['has_pdf'] for r in rows)} have a text layer)")
    rows.sort(key=lambda r: (r["date"] or "", r["id"]), reverse=True)
    write_normalized(ctx, META, rows, len(rows), extra={"about": about, "pdfs": sum(r["has_pdf"] for r in rows)})
    return 0
