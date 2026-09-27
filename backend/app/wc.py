"""CDSCO Written Confirmations (API exports to the EU) for the Playground.

Reads data/sources/cdsco_wc.json (redis-loader/sources/cdsco_wc.py) and serves the letters from
data/docs/cdsco_wc/<id>.pdf. The file is re-read only when it changes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from .config import settings

_cache: dict[str, Any] = {"mtime": None, "data": {}}
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def _root() -> Path:
    return settings.data_dir


def _load() -> dict[str, Any]:
    p = _root() / "sources" / "cdsco_wc.json"
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != m:
        try:
            _cache["data"] = json.loads(p.read_text(encoding="utf-8"))
            _cache["mtime"] = m
        except (OSError, json.JSONDecodeError):
            return {}
    return _cache["data"]


def docs_dir() -> Path:
    return _root() / "docs" / "cdsco_wc"


def _has(rid: str) -> bool:
    return (docs_dir() / f"{rid}.pdf").is_file()


def _snippet(text: str, q: str, width: int = 90) -> Optional[str]:
    i = text.lower().find(q)
    if i < 0:
        return None
    a, b = max(0, i - width), min(len(text), i + len(q) + width)
    return ("…" if a else "") + re.sub(r"\s+", " ", text[a:b]).strip() + ("…" if b < len(text) else "")


def _row(r: dict[str, Any], q: str = "") -> dict[str, Any]:
    out = {k: r.get(k) for k in ("id", "kind", "wc", "wc_raw", "company", "products", "items", "date", "size_kb", "valid_until", "latest")}
    out["has_pdf"] = _has(r["id"])
    out["source_url"] = r.get("pdf_url") or r.get("download")
    if q and r.get("text") and q not in " ".join(str(r.get(k) or "") for k in ("wc", "wc_raw", "company", "products")).lower():
        out["hit"] = _snippet(r["text"], q)
    return out


def listing(q: str = "", kind: str = "wc", year: str = "", latest: bool = False, page: int = 1, size: int = 25) -> dict[str, Any]:
    d = _load()
    rows = d.get("data") or []
    if not rows:
        return {"available": False}
    q = q.strip().lower()
    years = Counter((r.get("date") or "")[:4] for r in rows if r.get("kind") == "wc" and r.get("date"))
    sel = [r for r in rows if (kind == "all" or r.get("kind") == kind)]
    if year:
        sel = [r for r in sel if (r.get("date") or "").startswith(year)]
    if latest:
        sel = [r for r in sel if r.get("latest", True)]
    if q:
        def hay(r: dict[str, Any]) -> str:
            return " ".join(str(r.get(k) or "") for k in ("wc", "wc_raw", "company", "products", "text")).lower()
        sel = [r for r in sel if q in hay(r)]
    pages = max(1, -(-len(sel) // size))
    page = min(page, pages)
    wcs = [r for r in rows if r.get("kind") == "wc"]
    return {
        "available": True,
        "meta": {k: d.get(k) for k in ("title", "publisher", "url", "retrieved_at", "records")},
        "stats": {
            "letters": len(wcs),
            "numbers": len({r["wc"] for r in wcs if r.get("wc")}),
            "companies": len({(r.get("company") or "").lower() for r in wcs if r.get("company")}),
            "notices": len(rows) - len(wcs),
            "pdfs": sum(1 for r in rows if _has(r["id"])),
            "with_text": sum(1 for r in rows if r.get("text")),
            "latest_date": max((r.get("date") or "" for r in wcs), default=None),
            "last_12m": sum(1 for r in wcs if (r.get("date") or "") >= _year_ago(d.get("retrieved_at"))),
        },
        "years": dict(sorted(years.items())),
        "total": len(sel), "page": page, "pages": pages,
        "items": [_row(r, q) for r in sel[(page - 1) * size: page * size]],
        "about": d.get("about") or [],
    }


def _year_ago(ts: Optional[str]) -> str:
    y = (ts or "0000")[:4]
    return f"{int(y) - 1:04d}{(ts or '')[4:10]}" if y.isdigit() else ""


def pdf_path(rid: str) -> Optional[Path]:
    if not _SAFE.match(rid or ""):
        return None
    p = docs_dir() / (rid if rid.endswith(".pdf") else f"{rid}.pdf")
    return p if p.is_file() else None


def record(rid: str) -> Optional[dict[str, Any]]:
    return next((r for r in (_load().get("data") or []) if r.get("id") == rid), None)
