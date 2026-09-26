"""Shared plumbing for the public-data fetchers.

Each source writes two things:

* data/raw/<source>/          the untouched download(s), kept for audit
* data/sources/<source>.json  a small normalised file the universe builder reads:
    {"source", "title", "publisher", "url", "retrieved_at", "records", "data": {...}}

and updates data/sources/manifest.json (one entry per source: last attempt,
last success, record count, status, error) which the admin Pipelines page shows.

HTTP uses only the standard library, sends If-None-Match / If-Modified-Since
from the previous download, and treats 304 as "unchanged".
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (compatible; nsq-platform-ingest/1.0; +https://github.com/)"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNREACHABLE = 2
EXIT_UNCHANGED = 3


def data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Unreachable(Exception):
    """The remote host could not be reached (network / DNS / proxy / 5xx)."""


class NotModified(Exception):
    """The remote file has not changed since the last download."""


@dataclass
class Ctx:
    name: str
    from_file: Optional[Path] = None
    force: bool = False
    limit: Optional[int] = None
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_dir(self) -> Path:
        p = data_dir() / "raw" / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def out_path(self) -> Path:
        p = data_dir() / "sources"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{self.name}.json"

    def log(self, msg: str) -> None:
        print(msg, flush=True)


# --- HTTP ---------------------------------------------------------------------

def _cache_file(raw_dir: Path) -> Path:
    return raw_dir / ".http-cache.json"


def http_get(url: str, *, params: Optional[dict] = None, timeout: int = 120, retries: int = 2,
             accept: str = "*/*", data: Optional[bytes] = None, headers: Optional[dict] = None) -> bytes:
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = Request(url, data=data, headers={"User-Agent": UA, "Accept": accept, **(headers or {})})
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                last = exc
                continue
            if exc.code >= 500 or exc.code in (403, 407, 429):
                raise Unreachable(f"HTTP {exc.code} from {url}") from exc
            raise
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise Unreachable(f"{url}: {exc}") from exc
    raise Unreachable(f"{url}: {last}")


def download(ctx: Ctx, url: str, filename: str, *, timeout: int = 300) -> Path:
    """Conditional GET into raw_dir/filename. Raises NotModified on 304."""
    dest = ctx.raw_dir / filename
    cache_path = _cache_file(ctx.raw_dir)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    headers = {"User-Agent": UA, "Accept": "*/*"}
    prev = cache.get(url, {})
    if dest.exists() and not ctx.force:
        if prev.get("etag"):
            headers["If-None-Match"] = prev["etag"]
        if prev.get("last_modified"):
            headers["If-Modified-Since"] = prev["last_modified"]
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(tmp, dest)
            cache[url] = {"etag": resp.headers.get("ETag", ""), "last_modified": resp.headers.get("Last-Modified", ""),
                          "fetched_at": now_iso(), "bytes": dest.stat().st_size}
            cache_path.write_text(json.dumps(cache, indent=1))
            ctx.log(f"downloaded {url} → {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
            return dest
    except HTTPError as exc:
        if exc.code == 304:
            raise NotModified(url) from exc
        if exc.code >= 500 or exc.code in (403, 407, 429):
            raise Unreachable(f"HTTP {exc.code} from {url}") from exc
        raise
    except (URLError, TimeoutError, OSError) as exc:
        raise Unreachable(f"{url}: {exc}") from exc


# --- outputs ------------------------------------------------------------------

def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def write_normalized(ctx: Ctx, meta: dict[str, Any], data: Any, records: int, extra: Optional[dict] = None) -> None:
    payload = {
        "source": ctx.name,
        "title": meta.get("title", ctx.name),
        "publisher": meta.get("publisher", ""),
        "url": meta.get("url", ""),
        "retrieved_at": now_iso(),
        "records": records,
        **(extra or {}),
        "data": data,
    }
    write_json_atomic(ctx.out_path, payload)
    ctx.log(f"wrote {ctx.out_path.name}: {records:,} records")


def read_normalized(name: str) -> Optional[dict[str, Any]]:
    p = data_dir() / "sources" / f"{name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def manifest_path() -> Path:
    return data_dir() / "sources" / "manifest.json"


def read_manifest() -> dict[str, Any]:
    p = manifest_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_manifest(name: str, **fields: Any) -> None:
    m = read_manifest()
    entry = m.get(name, {})
    entry.update(fields)
    m[name] = entry
    write_json_atomic(manifest_path(), m)
