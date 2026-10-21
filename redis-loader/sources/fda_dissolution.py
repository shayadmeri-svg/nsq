"""FDA Dissolution Methods Database: the official dissolution test for each drug product.

One page lists every method FDA recommends for generic products (drug, dosage form, USP apparatus, speed,
medium, volume, sampling times, date updated). This keeps the whole table and indexes it by ingredient key,
so the Lab's dissolution and bioequivalence models start from FDA's method instead of generic defaults, and
Investigate can show the method next to a dissolution failure.

    data: {ingredient_key: [{drug, dosage_form, apparatus, rpm, medium, volume_ml, times_min, updated, combination}]}
"""

from __future__ import annotations

import html as _html
import re
from typing import Any

from .common import Ctx, download, write_normalized

URL = "https://www.accessdata.fda.gov/scripts/cder/dissolution/dsp_getallData.cfm"
META = {
    "title": "FDA Dissolution Methods Database",
    "publisher": "U.S. Food and Drug Administration (CDER, Division of Biopharmaceutics)",
    "url": URL,
    "page": "https://www.accessdata.fda.gov/scripts/cder/dissolution/index.cfm",
    "cadence": "quarterly; checked weekly",
    "feeds": ["Dissolution method per drug product (Lab, Investigate)"],
}


def _cells(row: str) -> list[str]:
    return [_html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]


def _num(s: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group(0)) if m else None


def parse(html: str) -> list[dict[str, Any]]:
    rows = [_cells(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)]
    out = []
    for c in rows:
        if len(c) < 8 or not c[0] or c[0] == "Drug Name":
            continue
        drug, form, app, rpm, medium, vol, times, updated = c[:8]
        combo = bool(re.search(r"[;/]| and ", drug))
        out.append({"drug": drug, "dosage_form": form, "apparatus": app, "rpm": _num(rpm) if rpm else None, "rpm_text": rpm,
                    "medium": medium, "volume_ml": _num(vol) if vol and not combo else None, "volume_text": vol,
                    "times_min": [float(x) for x in re.findall(r"\d+(?:\.\d+)?", times)] if times and not combo else [],
                    "times_text": times, "updated": updated, "combination": combo})
    return out


def run(ctx: Ctx) -> int:
    import ingredients as ing  # core/

    path = ctx.from_file or download(ctx, URL, "dissolution_all.html")
    rows = parse(path.read_text(encoding="utf-8", errors="replace"))
    data: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["combination"]:
            continue
        k = ing.ingredient_key(r["drug"])
        if k:
            data.setdefault(k, []).append(r)
            base = k.split()[0]
            if base != k:
                data.setdefault(base, []).append(r)
    write_normalized(ctx, META, data, len(rows), extra={"methods": len(rows), "ingredients": len(data)})
    return len(rows)
