"""Tenant isolation: an organisation's users never see another organisation's (or manufacturer's) data.

For users of an organisation (not platform staff):
  * Anything addressed by id — a manufacturer key, a registry plant, a Written Confirmation — must be their own
    (checked in the endpoints with `own_key`, `own_plant`, `own_company`).
  * Lists of plants are cut to their own plants (`keep_own_plants`).
  * Every JSON response of a gated router passes through `scrub`: any string that names another manufacturer,
    company, plant or licensee is replaced by a stable pseudonym ("Other manufacturer · 7F3A"), and values under
    name-like keys ("manufacturer", "company", …) are pseudonymised unless they are the organisation's own.
    Aggregates (counts, shares, national totals) are kept: they are public statistics, not a company's record.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from . import data
from .models import PLATFORM_ROLES, Org, User

_KEY = (os.environ.get("PSEUDONYM_KEY") or secrets.token_hex(16)).encode()
_lock = threading.Lock()
_peer_cache: dict[str, Any] = {"key": None, "names": frozenset(), "plants": frozenset()}

# values under these keys name a company or site
NAME_KEYS = frozenset({"manufacturer", "manufacturers_named", "company", "maker", "manufactured_by", "firm", "holder",
                       "applicant", "licensee", "loan_licensees", "site_name", "mfg_company", "company_name", "mfr"})
# values under these keys are never company data of a peer (patent originators, brands, source labels)
EXEMPT_KEYS = frozenset({"originator", "brand_name", "brand", "api_name", "publisher", "source", "url", "title", "licence"})
_GENERIC = frozenset({"unknown", "other", "others", "na", "n a", "nil", "none", "not known", "not mentioned", "various"})


def norm(s: Any) -> str:
    s = str(s or "").lower()
    s = re.sub(r"^\s*m\s*/\s*s\.?\s*", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _plant_names(p: dict[str, Any]) -> list[str]:
    return [p.get("name") or "", *(p.get("aliases") or []), *(p.get("loan_licensees") or [])]


def _peer_index() -> tuple[frozenset[str], frozenset[str]]:
    """(every company / manufacturer / plant name and manufacturer key, every registry plant id), normalised."""
    from . import plants as registry, wc

    df = data.frame()
    try:
        reg = registry.registry()
    except Exception:
        reg = {"plants": {}}
    w = wc._load()
    cdmo = data.cdmo()["plants"]
    key = (id(df), id(reg), id(w), id(cdmo))
    if _peer_cache["key"] == key:
        return _peer_cache["names"], _peer_cache["plants"]
    with _lock:
        names: set[str] = set()
        if not df.empty:
            for col in ("Mfg_Company_Canonical", "Mfg_Company", "Manufactured By", "Mfg_Ontology_Key"):
                if col in df.columns:
                    names.update(norm(v) for v in df[col].dropna().astype(str).unique())
        for p in reg["plants"].values():
            names.update(norm(n) for n in _plant_names(p))
        for r in (w.get("data") or {}).values() if isinstance(w.get("data"), dict) else (w.get("data") or []):
            names.add(norm(r.get("company")))
        for a in cdmo.values():
            ref = (getattr(a, "reference", None) or {})
            names.update(norm(x) for x in (getattr(a, "site_name", ""), ref.get("company")))
        # words that are not company names even if a messy record used them as one
        vocab: set[str] = set(_GENERIC)
        if not df.empty:
            for col in ("Product_Name_Canonical", "Name of Product", "Form type", "Drug type", "Failure_Category_Primary", "_state"):
                if col in df.columns:
                    vocab.update(norm(v) for v in df[col].dropna().astype(str).unique())
        out = frozenset(n for n in names if len(n) >= 4 and n not in vocab)
        _peer_cache.update(key=key, names=out, plants=frozenset(reg["plants"]))
        return out, _peer_cache["plants"]


@dataclass
class Tenant:
    org_id: int
    keys: frozenset[str]
    names: frozenset[str]  # normalised own names
    plants: frozenset[str]  # own registry plant ids
    profiles: frozenset[str]  # own cdmo plant profile ids
    peer_names: frozenset[str] = field(default=frozenset())
    all_plants: frozenset[str] = field(default=frozenset())

    def own_name(self, s: Any) -> bool:
        return norm(s) in self.names

    def pseudo(self, s: Any) -> str:
        h = hmac.new(_KEY, f"{self.org_id}:{norm(s)}".encode(), hashlib.sha256).hexdigest()[:4].upper()
        return f"Other manufacturer · {h}"

    def is_peer(self, s: Any) -> bool:
        n = norm(s)
        return bool(n) and n in self.peer_names and n not in self.names


_tenants: dict[tuple, Tenant] = {}


def for_user(db: Session, user: User) -> Optional[Tenant]:
    """None for platform staff (they see everything); a Tenant for an organisation's users."""
    if user.role in PLATFORM_ROLES:
        return None
    org: Optional[Org] = user.org
    if org is None:
        return Tenant(org_id=0, keys=frozenset(), names=frozenset(), plants=frozenset(), profiles=frozenset(),
                      peer_names=_peer_index()[0], all_plants=_peer_index()[1])
    peer_names, all_plants = _peer_index()
    ck = (org.id, tuple(org.ontology_keys or []), tuple(org.plant_ids or []), org.name, id(peer_names))
    t = _tenants.get(ck)
    if t is not None:
        return t
    from . import plants as registry, sites

    keys = frozenset(org.ontology_keys or [])
    names: set[str] = {norm(org.name), *(norm(k) for k in keys)}
    df = data.org_frame(list(keys))
    for col in ("Mfg_Company_Canonical", "Mfg_Company", "Manufactured By"):
        if not df.empty and col in df.columns:
            names.update(norm(v) for v in df[col].dropna().astype(str).unique())
    own_plants: set[str] = set()
    try:
        reg = registry.registry()
        for s in sites.directory():
            if s["ontology_key"] in keys:
                names.add(norm(s["company"]))
                own_plants.update((reg["links"].get(s["id"]) or {}).get("plant_ids") or [])
    except Exception:
        reg = {"plants": {}}
    profiles = frozenset(org.plant_ids or [])
    cdmo = data.cdmo()["plants"]
    for pid in profiles:
        a = cdmo.get(pid)
        if a is None:
            continue
        ref = getattr(a, "reference", None) or {}
        names.update(norm(x) for x in (getattr(a, "site_name", ""), ref.get("company")))
        rp = ref.get("registry_plant")
        if isinstance(rp, dict) and rp.get("id"):
            own_plants.add(rp["id"])
        elif isinstance(rp, str):
            own_plants.add(rp)
    for pid in own_plants:
        p = reg["plants"].get(pid)
        if p:
            names.update(norm(n) for n in _plant_names(p))
    names.discard("")
    t = Tenant(org_id=org.id, keys=keys, names=frozenset(names), plants=frozenset(own_plants), profiles=profiles,
               peer_names=peer_names, all_plants=all_plants)
    if len(_tenants) > 200:
        _tenants.clear()
    _tenants[ck] = t
    return t


# --- checks used by endpoints ------------------------------------------------------------------

def own_key(t: Optional[Tenant], key: str) -> None:
    if t is not None and key not in t.keys:
        raise HTTPException(404, "Not found in your organisation's records.")


def own_plant(t: Optional[Tenant], plant_id: str) -> None:
    if t is not None and plant_id not in t.plants:
        raise HTTPException(404, "Plant not found in your organisation.")


def own_company(t: Optional[Tenant], name: Any) -> bool:
    return t is None or t.own_name(name)


def keep_own_plants(t: Optional[Tenant], obj: Any) -> Any:
    """Drop list entries that are other registry plants (dicts whose id is a registry plant id not ours)."""
    if t is None:
        return obj
    if isinstance(obj, dict):
        return {k: keep_own_plants(t, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [keep_own_plants(t, x) for x in obj
                if not (isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"] in t.all_plants and x["id"] not in t.plants)]
    return obj


# --- response scrubbing -------------------------------------------------------------------------

_FIELD = re.compile(r"^[a-z0-9_]+$")
# keys whose single-word values may be a maker's name (elsewhere a one-word match is more likely an ordinary word:
# "anchor", "product" … are also company names)
_LABEL_KEYS = frozenset({"name", "key", "label", "row", "rows", "source_name", "target_name"})


def scrub(t: Optional[Tenant], obj: Any) -> Any:
    if t is None:
        return obj

    def val(v: Any, named: bool, pkey: str) -> Any:
        if isinstance(v, str):
            if named and v.strip() and norm(v) not in _GENERIC and not t.own_name(v):
                return t.pseudo(v)
            if t.is_peer(v) and (" " in norm(v) or pkey in _LABEL_KEYS):
                return t.pseudo(v)
            return v
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                ks = str(k)
                kl = ks.lower()
                nk = t.pseudo(ks) if (not _FIELD.match(ks) and t.is_peer(ks)) else ks  # field names are never renamed
                out[nk] = x if kl in EXEMPT_KEYS else val(x, kl in NAME_KEYS, kl)
            return out
        if isinstance(v, list):
            return [val(x, named, pkey) for x in v]
        return v

    return val(obj, False, "")


def tenant_of(request: Request) -> Optional[Tenant]:
    return getattr(request.state, "tenant", None)


class TenantRoute(APIRoute):
    """Route class for gated routers: JSON responses to an organisation's users are scrubbed."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def run(request: Request) -> Response:
            resp = await handler(request)
            user = getattr(request.state, "user", None)
            if user is None or user.role in PLATFORM_ROLES:
                return resp
            if not (resp.headers.get("content-type") or "").startswith("application/json"):
                return resp
            t = getattr(request.state, "tenant", None)
            if t is None:
                from .db import SessionLocal
                with SessionLocal() as db:
                    t = for_user(db, db.merge(user, load=True))
            body = json.loads(resp.body)
            out = json.dumps(scrub(t, body), separators=(",", ":"), default=str).encode()
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length",)}
            return Response(out, status_code=resp.status_code, headers=headers, media_type="application/json")

        return run
