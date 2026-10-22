"""The Japanese Pharmacopoeia (English version, MHLW): the tests and limits of each tablet and capsule monograph.

MHLW publishes the English JP free on its website under the Public Data License 1.0 (reuse, including commercial,
with attribution "Source: Ministry of Health, Labour and Welfare website (URL)"; values extracted here are marked as
processed by Eurveda, never as MHLW's own text). The English text is a translation; the Japanese original is
authentic. This reads the current edition's Official Monographs (A–L, M–Z) and its Supplements (a supplement's text
replaces the main edition's), splits the monographs and, from each tablet / capsule monograph, keeps:

    assay        contain not less than X% and not more than Y% of the labeled amount
    dissolution  apparatus and speed, medium and its volume (and pH for JP's standard fluids), time, Q
    disintegration  a time the monograph sets

Every monograph's ingredient name is resolved through core/identity.py, and the run's coverage — which names mapped,
how, and which did not — is stored with the data.

    data: {molecule_key: {"found": True, "monographs": [{title, form, ingredients, combination, pdf, page, assay,
                                                        dissolution, disintegration, supplement}]}}
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path
from typing import Any, Optional

from .common import Ctx, NotModified, data_dir, download, http_get, write_normalized

PAGE = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000066597.html"
BASE = "https://www.mhlw.go.jp"
LICENCE = {"name": "Public Data License 1.0 (Japan)", "url": "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
           "attribution": f"Source: Ministry of Health, Labour and Welfare website ({PAGE}); limits extracted and processed by Eurveda"}
META = {
    "title": "The Japanese Pharmacopoeia (MHLW, English version)",
    "publisher": "Ministry of Health, Labour and Welfare, Japan",
    "url": PAGE,
    "page": PAGE,
    "cadence": "an edition every five years with supplements; checked weekly (PDFs re-read only when they change)",
    "feeds": ["Assay and dissolution limits per tablet / capsule monograph (twin specifications, Lab dissolution)"],
    "licence": LICENCE["name"],
}

FORMS = ("orally disintegrating tablets", "extended-release tablets", "delayed-release tablets", "enteric-coated tablets",
         "film-coated tablets", "chewable tablets", "dispersible tablets", "effervescent tablets", "tablets",
         "extended-release capsules", "enteric-coated capsules", "capsules")
IR_FORMS = {"tablets", "film-coated tablets", "orally disintegrating tablets", "chewable tablets", "dispersible tablets", "capsules"}
# JP's standard dissolution media (JP 6.10)
MEDIUM_PH = [(r"1st fluid for dissolution test", 1.2), (r"2nd fluid for dissolution test", 6.8)]
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")


def editions(page_html: str) -> list[tuple[str, str]]:
    """(label, pdf url) of the newest edition's Official Monographs and Supplements, in the order they apply."""
    sections = re.split(r"<h[2-4][^>]*>", page_html)
    newest = None
    for sec in sections:
        m = re.match(r"\s*(?:<[^>]+>)*\s*The Japanese Pharmacopoeia (\d+)(?:st|nd|rd|th) edition", sec)
        if m and (newest is None or int(m.group(1)) > newest[0]):
            newest = (int(m.group(1)), sec)
    if not newest:
        raise RuntimeError("JP: no edition found on the MHLW page")
    out = []
    for href, txt in re.findall(r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>', newest[1], re.S):
        label = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", txt))).strip()
        if re.search(r"Official Monographs|Supplement", label):
            out.append((label, href if href.startswith("http") else BASE + href))
    out.sort(key=lambda x: (x[0].startswith("Supplement"), x[0]))  # main text first, then Supplement I, II …
    return out


def pdf_text(path: Path) -> list[str]:
    import pypdfium2 as pdfium  # installed with pdfplumber

    pdf = pdfium.PdfDocument(str(path))
    try:
        return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()


def _clean_page(t: str) -> str:
    t = re.sub(r"(\d)z", r"\1%", t)  # the PDF's font maps % to z: "95.0z" is 95.0%
    t = t.replace("￾", "").replace("­", "")
    lines = [ln for ln in t.splitlines()
             if not re.match(r"^\s*JP XVI+I?\s+(Official Monographs|Supplement)", ln)
             and not ln.startswith(("The JP Drugs are to be tested", "General Rules for Crude Drugs, General Rules for Preparations"))
             and "for their conformity to the Japanese Pharmacopoeia" not in ln]
    return "\n".join(lines)


def split_monographs(pages: list[str]) -> list[dict[str, Any]]:
    """Monographs start with the English title on one line and the Japanese name on the next."""
    lines: list[tuple[int, str]] = []
    for i, p in enumerate(pages, 1):
        lines += [(i, ln.strip()) for ln in _clean_page(p).splitlines() if ln.strip()]
    starts = [j for j in range(len(lines) - 1)
              if not _CJK.search(lines[j][1]) and _CJK.search(lines[j + 1][1]) and not re.search(r"[a-z]", _CJK.sub("", lines[j + 1][1]))
              and re.match(r"^[A-Z][A-Za-z0-9 ,\-()'.]+$", lines[j][1]) and len(lines[j][1]) < 90]
    out = []
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        body = " ".join(ln for _, ln in lines[a + 2:b])
        body = re.sub(r"(\w)- (\w)", r"\1\2", body)  # words hyphenated across lines
        out.append({"title": lines[a][1], "page": lines[a][0], "text": body})
    return out


def split_title(title: str) -> Optional[tuple[list[str], str]]:
    low = title.lower()
    for form in FORMS:
        if low.endswith(" " + form):
            head = title[: -len(form)].strip()
            return [p.strip() for p in re.split(r",\s*|\s+and\s+", head) if p.strip()], form
    return None


_NUM = r"(\d+(?:\.\d+)?)"


def parse_assay(text: str) -> Optional[dict[str, Any]]:
    m = re.search(rf"contains? not less than {_NUM}\s*%\s*and not more than {_NUM}\s*%\s*of the labeled amount[^.]*\.", text)
    return {"lo": float(m.group(1)), "hi": float(m.group(2)), "text": m.group(0)} if m else None


def _section(text: str, head: str) -> Optional[str]:
    m = re.search(head, text)
    if not m:
        return None
    rest = text[m.start():]
    nxt = re.search(r"\s(Assay|Uniformity of dosage units|Disintegration|Dissolution|Purity|Identification|Containers and storage|"
                    r"Particle size|Water|Loss on drying|Foreign insoluble|Microbial)\s(<\d|[A-Z][a-z])", rest[len(m.group(0)):])
    return rest[: len(m.group(0)) + nxt.start()] if nxt else rest[:2500]


def medium_ph(medium: str) -> Optional[float]:
    for rx, ph in MEDIUM_PH:
        if re.search(rx, medium, re.I):
            return ph
    m = re.search(r"pH\s*" + _NUM, medium)
    return float(m.group(1)) if m else None


def parse_dissolution(text: str) -> Optional[dict[str, Any]]:
    sec = _section(text, r"Dissolution <6\.10>")
    if not sec:
        return None
    out: dict[str, Any] = {"text": sec[:1500]}
    app = re.search(r"at\s*(\d+)\s*revolutions per minute according to the (Paddle|Basket|Flow-through cell)", sec)
    if app:
        out["rpm"], out["apparatus"] = float(app.group(1)), app.group(2).lower()
    med = re.search(r"using\s*(\d+)\s*mL of (.+?) as the dissolution medium", sec)
    if med:
        out["volume_ml"], out["medium"] = float(med.group(1)), med.group(2).strip()
        out["ph"] = medium_ph(out["medium"])
    tq = re.findall(r"dissolution rates? in\s*(\d+)\s*minutes.{0,240}?(?:is|are) not less than\s*" + _NUM + r"\s*%", sec)
    if tq:
        out["time_min"], out["q_pct"] = float(tq[0][0]), float(tq[0][1])
        if len(tq) > 1:
            out["variants"] = [{"time_min": float(t), "q_pct": float(q)} for t, q in tq]  # e.g. per strength
    out["conditions_given"] = all(k in out for k in ("rpm", "volume_ml", "time_min"))
    return out


def parse_disintegration(text: str) -> Optional[dict[str, Any]]:
    sec = _section(text, r"Disintegration <6\.09>")
    if not sec:
        return None
    m = re.search(r"(\d+)\s*minutes", sec)
    return {"max_min": float(m.group(1)) if m else None, "text": sec[:500]}


def run(ctx: Ctx) -> int:
    import identity  # core/
    import ingredients as ing  # core/

    page = http_get(PAGE, timeout=60).decode("utf-8", errors="replace")
    pdfs = editions(page)
    ctx.log(f"JP: {len(pdfs)} PDFs for the current edition: " + "; ".join(lbl for lbl, _ in pdfs))
    resolver = identity.load(data_dir())
    by_title: dict[str, dict[str, Any]] = {}
    for label, url in pdfs:
        name = url.rsplit("/", 1)[-1]
        try:
            path = download(ctx, url, name)
        except NotModified:
            path = ctx.raw_dir / name
        pages = pdf_text(path)
        n = 0
        for mono in split_monographs(pages):
            st = split_title(mono["title"])
            if not st:
                continue
            ingredients, form = st
            rec = {"title": mono["title"], "form": form, "ingredients": ingredients, "combination": len(ingredients) > 1,
                   "immediate_release": form in IR_FORMS, "pdf": url, "page": mono["page"], "url": f"{url}#page={mono['page']}",
                   "supplement": label if label.startswith("Supplement") else None,
                   "assay": parse_assay(mono["text"]), "dissolution": parse_dissolution(mono["text"]),
                   "disintegration": parse_disintegration(mono["text"])}
            by_title[mono["title"].lower()] = rec  # a supplement's monograph replaces the main edition's
            n += 1
        ctx.log(f"  {label}: {len(pages)} pages, {n} tablet / capsule monographs")

    data: dict[str, Any] = {}
    names = []
    for rec in by_title.values():
        for ingr in rec["ingredients"]:
            names.append(ingr)
            m = resolver.resolve(ingr, online=True)
            key = m.key if m else ing.ingredient_key(ingr)
            entry = data.setdefault(key, {"found": True, "tracked": bool(m), "monographs": []})
            entry["monographs"].append({**rec, "matched": {"method": m.method, "via": m.via} if m else None})
    cov = identity.coverage(resolver, names, online=True)
    ctx.log(f"JP: {len(by_title)} monographs; {cov['mapped']}/{cov['entries']} ingredient names map to a tracked molecule "
            f"({', '.join(f'{k} {v}' for k, v in cov['by_method'].items() if v)}); "
            f"tracked molecules covered {len(cov['tracked_covered'])}/{cov['tracked_total']}")
    write_normalized(ctx, META, data, len(by_title), extra={"licence": LICENCE, "pdfs": [{"label": lbl, "url": u} for lbl, u in pdfs],
                                                            "coverage": cov})
    return len(by_title)
