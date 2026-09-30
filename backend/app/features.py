"""Playground feature registry and who may use what.

Three layers, checked on the server for every request (hiding a tab is only cosmetic):
  1. REGISTRY: every Playground feature, with the API paths it uses.
  2. Entitlements (platform admins): which features an organisation has.
  3. Visibility (org admin): which of those features each member persona sees. Org admins see every
     entitled feature; platform staff see everything.

A request to a gated path passes when the user's effective features include ANY feature that owns the
path's longest matching prefix. A gated path that no feature owns is platform-only (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import PERSONAS, PLATFORM_ROLES, Org, OrgFeatures, User
from .security import current_user


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    group: str
    hint: str
    api: tuple[str, ...]
    # "national": aggregates of public data (other makers pseudonymised for org users);
    # "own": only the organisation's own records are returned to org users.
    scope: str = "national"
    base: bool = False  # part of the base package an organisation gets until an admin sets its features
    notes: str = ""
    requires: tuple[str, ...] = field(default=())


REGISTRY: tuple[Feature, ...] = (
    Feature("explore", "NSQ explorer", "NSQ analytics", "All-India alerts: map, heatmaps, flows",
            ("/api/playground/cube", "/api/playground/facets", "/api/playground/geo/india"), base=True,
            notes="Manufacturer rows in heatmaps and top lists are pseudonymised, except your own."),
    Feature("ledger", "Ledger", "NSQ analytics", "Alert-level table with export",
            ("/api/playground/ledger", "/api/playground/facets"), scope="own",
            notes="Org users only get their own organisation's alerts."),
    Feature("insights", "Insights", "NSQ analytics", "Patterns the raw alerts don't show",
            ("/api/playground/insights", "/api/playground/survival"), base=True),
    Feature("forensics", "Failure forensics", "NSQ analytics", "Why products fail NSQ, and portfolio risk",
            ("/api/playground/forensics", "/api/playground/investigate/search"), base=True,
            notes="Portfolio compares only with your own organisation's record."),
    Feature("investigate", "Investigate", "NSQ analytics", "Product and manufacturer NSQ history with diagnosis",
            ("/api/playground/investigate", "/api/playground/investigate/search"), scope="own",
            notes="Manufacturer drill-down is limited to your own organisation."),
    Feature("world", "Regulation map", "Regulatory", "India vs US vs EU vs Africa",
            ("/api/playground/world",), base=True),
    Feature("wc", "Written confirmations", "Regulatory", "CDSCO Written Confirmations for API exports to the EU",
            ("/api/playground/wc",), scope="own", notes="Only letters issued to your organisation."),
    Feature("molecule", "Molecule workbench", "Molecules & plants", "Passport, demand, scores, monographs, plant fit",
            ("/api/playground/molecule", "/api/playground/world", "/api/plants", "/api/plants/facets", "/api/plants/for-molecule"),
            notes="Plant fit and makers are limited to your own plants."),
    Feature("plants", "Plants", "Molecules & plants", "CDSCO plant registry with NSQ record",
            ("/api/plants", "/api/plants/facets", "/api/plants/for-molecule"), scope="own", notes="Only your organisation's plants; national totals stay visible."),
    Feature("health", "Health & trade", "Market signals", "NFHS disease burden, IDSP outbreaks, UN Comtrade trade",
            ("/api/playground/signals", "/api/playground/geo/india"), base=True),
    Feature("medicines", "Medicines", "Science", "Composition from open databases, gaps",
            ("/api/medicines", "/api/lab/structure")),
    Feature("process", "Lab", "Science", "Structure-based molecule and process models",
            ("/api/lab", "/api/lab/structure", "/api/process")),
    Feature("reactions", "Reaction lab", "Science", "Batch-reactor kinetics, yield map, thermal safety",
            ("/api/lab/reactions", "/api/lab/engines")),
)

BY_ID = {f.id: f for f in REGISTRY}
ALL_IDS = tuple(f.id for f in REGISTRY)
BASE_IDS = tuple(f.id for f in REGISTRY if f.base)


def features_for_path(path: str) -> set[str]:
    """Features owning the longest registry prefix that matches `path` (segment-aligned)."""
    best, owners = -1, set()
    for f in REGISTRY:
        for p in f.api:
            if path == p or path.startswith(p + "/") or path.startswith(p + "."):
                if len(p) > best:
                    best, owners = len(p), {f.id}
                elif len(p) == best:
                    owners.add(f.id)
    return owners


def clean_ids(ids: Any) -> list[str]:
    return [i for i in ALL_IDS if i in set(ids or [])]


def org_settings(db: Session, org: Org) -> tuple[list[str], dict[str, list[str]], bool]:
    """(entitled, visibility, configured) for an organisation."""
    row = db.get(OrgFeatures, org.id)
    if row is None:
        return list(BASE_IDS), {}, False
    ent = clean_ids(row.entitled)
    vis = {p: [i for i in clean_ids(v) if i in ent] for p, v in (row.visibility or {}).items() if p in PERSONAS}
    return ent, vis, True


def effective(db: Session, user: User) -> list[str]:
    if user.role in PLATFORM_ROLES:
        return list(ALL_IDS)
    org = user.org
    if org is None or not org.is_active:
        return []
    ent, vis, _ = org_settings(db, org)
    if user.role == "org_admin":
        return ent
    allowed = vis.get(user.persona)
    return ent if allowed is None else [i for i in ent if i in allowed]


def gate(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Router dependency: the user must hold a feature that owns this path."""
    if user.role in PLATFORM_ROLES:
        return
    from . import tenant

    owners = features_for_path(request.url.path)
    mine = set(effective(db, user))
    request.state.features = mine
    request.state.tenant = tenant.for_user(db, user)
    if not owners or not (owners & mine):
        label = ", ".join(BY_ID[o].label for o in sorted(owners)) or "this tool"
        raise HTTPException(403, f"Your access doesn't include {label}. Ask your organisation admin.")


def registry_payload() -> list[dict[str, Any]]:
    return [{"id": f.id, "label": f.label, "group": f.group, "hint": f.hint, "scope": f.scope, "base": f.base, "notes": f.notes}
            for f in REGISTRY]


def set_entitled(db: Session, org: Org, ids: list[str], actor: str) -> OrgFeatures:
    row = db.get(OrgFeatures, org.id) or OrgFeatures(org_id=org.id, visibility={})
    row.entitled = clean_ids(ids)
    # visibility can never exceed what the organisation has
    row.visibility = {p: [i for i in clean_ids(v) if i in row.entitled] for p, v in (row.visibility or {}).items() if p in PERSONAS}
    row.updated_by = actor
    db.add(row)
    db.commit()
    return row


def set_visibility(db: Session, org: Org, vis: dict[str, Optional[list[str]]], actor: str) -> OrgFeatures:
    ent, _, configured = org_settings(db, org)
    row = db.get(OrgFeatures, org.id) or OrgFeatures(org_id=org.id, entitled=ent)
    bad = [i for v in vis.values() if v for i in v if i not in ent]
    if bad:
        raise HTTPException(400, f"Not available to this organisation: {', '.join(sorted(set(bad)))}")
    row.visibility = {p: clean_ids(v) for p, v in vis.items() if p in PERSONAS and v is not None}
    row.updated_by = actor
    db.add(row)
    db.commit()
    return row
