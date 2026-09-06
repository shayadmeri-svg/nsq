"""Tenant registry for the manufacturer app.

Each manufacturer is one tenant. The registry has two layers:

1. **Curated tenants** (``CURATED``) — hand-pinned entries with a verified
   ``ontology_key`` and display metadata. These take precedence and their
   registry keys are stable, so existing sign-ins / bookmarks keep working.
2. **Ontology tenants** — every company in ``nsq:ontology:companies``,
   turned into a Tenant at runtime. This is what makes the app actually
   multi-tenant instead of a one-entry tuple with a dropdown for show.

Tenant identity = the ontology key (``Mfg_Ontology_Key`` in the enriched NSQ
frame), which is ``normalize_company_name(raw)``. For the curated Regent
entry that is ``regent ajanta`` ("biotech" is dropped as legal-form noise by
``_LEGAL_STOP``). The key was re-pinned after the 2026-08-27 deterministic
rebuild re-keyed all Regent rows; the old pinned value
``regent ajanta biotech`` only existed in the pre-rebuild Redis state, which
is why the dashboard rendered its empty state. See the
manufacturer-binning-determinism memory.

A WARNING ABOUT ONTOLOGY TENANTS
--------------------------------
``normalize_company_name`` strips legal-form and location noise, which is
usually right ("Unicure India Limited" / "Ltd" / "Ltd." all collapse to
``unicure``) but sometimes over-collapses: in a 900-row sample, 332 of 545
keys were a single token, and the key ``j`` merged "J. M. Laboratories" and
"J.P Industries" — two different companies under one tenant. The registry
does not filter these out (a deliberate product call: full coverage over a
clean tail), so ``Tenant.raw_names`` carries the distinct raw strings each
key absorbed. Surface it: a tenant covering names that are not variants of
each other is a merge the user needs to see, not one the app should hide.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

# NB: company_ontology is imported lazily inside all_tenants(), not at module
# scope. tenants.py must stay importable with nothing but the stdlib — the
# curated registry has to resolve in contexts where shared/ is not on
# sys.path and Redis does not exist (unit tests, tooling, a cold container).

# Ontology tenants are re-read from Redis at most this often. Mirrors the
# enriched-frame TTL in data_loader / manufacturer_api.
REGISTRY_TTL_S = 300.0


@dataclass(frozen=True)
class Tenant:
    """A single manufacturer tenant.

    ``ontology_key`` is the value the enriched NSQ frame's
    ``Mfg_Ontology_Key`` column is filtered on. ``canonical`` / ``city``
    are display fallbacks used only when the live ontology record is
    missing from Redis. ``raw_names`` are the distinct "Manufactured By"
    spellings the ontology folded into this key — see the module docstring.
    """

    key: str           # registry key (also the NSQ_TENANT value)
    ontology_key: str  # Mfg_Ontology_Key value to filter the frame on
    canonical: str     # display name fallback
    city: str          # display city fallback
    raw_names: tuple[str, ...] = field(default=())


# Hand-pinned tenants. Keys here are permanent — never renamed by an
# ontology rebuild — so anything already signed in stays valid.
CURATED: tuple[Tenant, ...] = (
    Tenant(
        key="regent-ajanta-biotech",
        ontology_key="regent ajanta",
        canonical="Regent Ajanta Biotech",
        city="Haridwar",
    ),
)

# Back-compat alias: REGISTRY used to be the whole registry. Callers that
# want every tenant should use all_tenants(); this stays as the offline /
# Redis-down floor.
REGISTRY: tuple[Tenant, ...] = CURATED

_CURATED_BY_KEY: dict[str, Tenant] = {t.key: t for t in CURATED}
_CURATED_ONTOLOGY_KEYS: frozenset[str] = frozenset(t.ontology_key for t in CURATED)

# (expires_at_monotonic, tenants) — module-level so every request in a
# process shares one ontology read.
_cache: tuple[float, tuple[Tenant, ...]] | None = None


def _slug(value: str) -> str:
    """Ontology key -> URL-safe registry key ('marc lifesciences' -> 'marc-lifesciences')."""
    s = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return s or "unknown"


def _tenant_from_record(ontology_key: str, rec: dict) -> Tenant:
    aliases = rec.get("aliases") or []
    if isinstance(aliases, str):  # tolerate a legacy scalar
        aliases = [aliases]
    canonical = (rec.get("canonical_name") or "").strip() or ontology_key.title()
    return Tenant(
        key=_slug(ontology_key),
        ontology_key=ontology_key,
        canonical=canonical,
        city=(rec.get("city") or "").strip() or "—",
        raw_names=tuple(sorted({str(a).strip() for a in aliases if str(a).strip()})),
    )


def all_tenants(force_refresh: bool = False) -> tuple[Tenant, ...]:
    """Curated tenants first, then every company in the ontology.

    Falls back to CURATED alone when Redis is unreachable, so the app still
    signs in and renders rather than showing an empty manufacturer list.
    """
    global _cache
    now = time.monotonic()
    if not force_refresh and _cache is not None and now < _cache[0]:
        return _cache[1]

    try:
        from company_ontology import load_ontology

        ontology = load_ontology()
    except Exception:
        # No Redis: don't cache the failure for the full TTL, so the first
        # request after Redis comes back picks the real list up.
        return CURATED

    dynamic = [
        _tenant_from_record(key, rec)
        for key, rec in ontology.items()
        if key and key not in _CURATED_ONTOLOGY_KEYS
    ]
    dynamic.sort(key=lambda t: t.canonical.lower())
    tenants = CURATED + tuple(dynamic)
    _cache = (now + REGISTRY_TTL_S, tenants)
    return tenants


def get_tenant(key: str) -> Tenant | None:
    """Return the tenant for ``key`` (a registry key / NSQ_TENANT value),
    or None if unknown. Curated keys win over ontology-derived ones."""
    key = (key or "").strip()
    if not key:
        return None
    if key in _CURATED_BY_KEY:
        return _CURATED_BY_KEY[key]
    for t in all_tenants():
        if t.key == key:
            return t
    return None


def get_active_tenant() -> Tenant:
    """Resolve the active tenant from ``NSQ_TENANT``, defaulting to the
    first curated tenant when unset or unknown."""
    env = os.environ.get("NSQ_TENANT", "").strip()
    if env:
        tenant = get_tenant(env)
        if tenant is not None:
            return tenant
    return CURATED[0]
