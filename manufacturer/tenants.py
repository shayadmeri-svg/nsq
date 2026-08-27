"""Tenant registry for the manufacturer app.

Each manufacturer is one tenant. The app is config-driven: the active
tenant is selected by the ``NSQ_TENANT`` environment variable (defaulting
to the first registered tenant), so phase 1 ships a single tenant with
no selector UI. Onboarding a second tenant later means adding a
``Tenant`` entry here and (optionally) exposing a selector — nothing in
``tenant_scope.py`` or ``dashboard.py`` hardcodes the key.

Tenant identity = the ontology key (``Mfg_Ontology_Key`` in the enriched
NSQ frame), which for this tenant equals ``normalize_company_name(raw)``
= ``regent ajanta`` ("biotech" is dropped as legal-form noise by
``_LEGAL_STOP``). The key was re-pinned after the 2026-08-27
deterministic rebuild re-keyed all Regent rows; the old pinned value
``regent ajanta biotech`` only existed in the pre-rebuild Redis state,
which is why the dashboard rendered its empty state. See the
manufacturer-binning-determinism memory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Tenant:
    """A single manufacturer tenant.

    ``ontology_key`` is the value the enriched NSQ frame's
    ``Mfg_Ontology_Key`` column is filtered on. ``canonical`` / ``city``
    are display fallbacks used only when the live ontology record is
    missing from Redis.
    """

    key: str           # registry key (also the NSQ_TENANT value)
    ontology_key: str  # Mfg_Ontology_Key value to filter the frame on
    canonical: str     # display name fallback
    city: str          # display city fallback


REGISTRY: tuple[Tenant, ...] = (
    Tenant(
        key="regent-ajanta-biotech",
        ontology_key="regent ajanta",
        canonical="Regent Ajanta Biotech",
        city="Haridwar",
    ),
)

_BY_KEY: dict[str, Tenant] = {t.key: t for t in REGISTRY}


def get_tenant(key: str) -> Tenant | None:
    """Return the tenant for ``key`` (a registry key / NSQ_TENANT value),
    or None if unknown."""
    return _BY_KEY.get((key or "").strip())


def get_active_tenant() -> Tenant:
    """Resolve the active tenant from ``NSQ_TENANT``, defaulting to the
    first registered tenant when unset or unknown."""
    env = os.environ.get("NSQ_TENANT", "").strip()
    if env and env in _BY_KEY:
        return _BY_KEY[env]
    return REGISTRY[0]