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

# FDA's accessdata.fda.gov sits behind a bot filter that redirects clients it
# does not recognise as browsers to a 404 page, so send ordinary browser headers.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/csv,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# www.fda.gov's abuse detection, on the other hand, flags a browser User-Agent
# that arrives without the rest of a browser's fingerprint — a plain tool
# User-Agent works there. Each host gets the header set it accepts, and a
# download that lands on an "apology"/404 page is retried with the other set.
TOOL_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; nsq-platform-ingest/1.0)", "Accept": "*/*"}


def headers_for(url: str) -> dict[str, str]:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    return dict(TOOL_HEADERS if host in ("www.fda.gov", "fda.gov") else BROWSER_HEADERS)


def decode_text(raw: bytes) -> str:
    """Bytes -> text, handling UTF-16 (FDA's Purple Book export) and UTF-8 BOMs."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if len(raw) > 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")

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


class NotFound(Exception):
    """The URL answered 404/410 (the publisher moved or renamed the file)."""


class Blocked(Exception):
    """The publisher's bot / abuse detection refused the request (usually temporary)."""


def _is_block(url_or_msg: str) -> bool:
    return any(w in (url_or_msg or "") for w in ("apology", "abuse-detection"))


def download_first(ctx: "Ctx", urls: list[str], filename: str, *, timeout: int = 300) -> "Path":
    """Try candidate URLs in order; the first that downloads (or is unchanged) wins."""
    errors = []
    seen = set()
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        try:
            return download(ctx, u, filename, timeout=timeout)
        except NotFound as exc:
            errors.append(str(exc))
            ctx.log(f"  not found: {exc}")
    raise NotFound("; ".join(errors[-3:]) or "no candidate URLs")


def page_links(url: str, pattern: str) -> list[str]:
    """hrefs on an HTML page matching a regex (absolute URLs). Empty on any error."""
    import re as _re
    from urllib.parse import urljoin
    try:
        html = http_get(url, timeout=60, retries=0).decode("utf-8", errors="replace")
    except Exception:
        return []
    out = []
    for h in _re.findall(r'href=["\']([^"\']+)["\']', html, flags=_re.I):
        if _re.search(pattern, h, flags=_re.I):
            out.append(urljoin(url, h))
    return out


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
        base = headers_for(url)
        req = Request(url, data=data, headers={**base, **({"Accept": accept} if accept != "*/*" else {}), **(headers or {})})
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
    first = headers_for(url)
    other = dict(BROWSER_HEADERS if first is not None and first.get("User-Agent") == TOOL_HEADERS["User-Agent"] else TOOL_HEADERS)
    try:
        return _download(ctx, url, filename, first, timeout)
    except NotFound as exc:
        # Bot filters answer with a redirect to an apology / 404 page: try the other header set once.
        ctx.log(f"  {exc} — retrying with different request headers")
        try:
            return _download(ctx, url, filename, other, timeout)
        except NotFound as exc2:
            if _is_block(str(exc2)):
                raise Blocked(str(exc2)) from exc2
            raise


def _download(ctx: Ctx, url: str, filename: str, base_headers: dict[str, str], timeout: int) -> Path:
    dest = ctx.raw_dir / filename
    cache_path = _cache_file(ctx.raw_dir)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    headers = dict(base_headers)
    prev = cache.get(url, {})
    if dest.exists() and not ctx.force:
        if prev.get("etag"):
            headers["If-None-Match"] = prev["etag"]
        if prev.get("last_modified"):
            headers["If-Modified-Since"] = prev["last_modified"]
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
            if "apology" in (final or "") or "abuse-detection" in (final or ""):
                raise NotFound(f"blocked: {url} redirected to {final}")
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
        final = exc.geturl() if hasattr(exc, "geturl") else url
        where = url if final in (None, url) else f"{url} (redirected to {final})"
        if exc.code >= 500 or exc.code in (403, 407, 429):
            raise Unreachable(f"HTTP {exc.code} from {where}") from exc
        raise NotFound(f"HTTP {exc.code} from {where}") from exc
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
