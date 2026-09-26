"""User, organisation and invite management + audit log + admin overview.

Scoping rules
-------------
* super_admin — everything, including other super admins.
* admin       — every org and user except super admins; cannot grant super_admin.
* org_admin   — users of their own org only, roles member/org_admin only.
* member      — nothing here.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import data, insights
from ..audit import audit
from ..config import settings
from ..db import get_db
from ..models import (
    PERSONAS, PLATFORM_ROLES, ROLES, AuditLog, Invite, JobRun, Org, Plant, User, UserSession, utcnow,
)
from ..security import (
    _aware, current_user, hash_password, new_token, require_platform, validate_password,
)
from .auth import org_brief
from .orgs import org_payload

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- scoping ------------------------------------------------------------------

def _require_manager(user: User = Depends(current_user)) -> User:
    if user.role not in (*PLATFORM_ROLES, "org_admin"):
        raise HTTPException(403, "You do not have access to user management.")
    return user


def _assignable_roles(actor: User) -> tuple[str, ...]:
    if actor.role == "super_admin":
        return ROLES
    if actor.role == "admin":
        return ("admin", "org_admin", "member")
    return ("org_admin", "member")


def _check_target(actor: User, role: str, org_id: Optional[int]) -> None:
    if role not in ROLES:
        raise HTTPException(400, f"Unknown role {role!r}.")
    if role not in _assignable_roles(actor):
        raise HTTPException(403, f"You cannot assign the {role} role.")
    if role in ("org_admin", "member") and org_id is None:
        raise HTTPException(400, "Organisation users need an organisation.")
    if actor.role == "org_admin" and org_id != actor.org_id:
        raise HTTPException(403, "You can only manage users of your own organisation.")


def _check_can_edit(actor: User, target: User) -> None:
    if actor.role == "super_admin":
        return
    if target.role == "super_admin":
        raise HTTPException(403, "Only a super admin can change a super admin.")
    if actor.role == "admin":
        return
    if actor.role == "org_admin" and target.org_id == actor.org_id and target.role in ("org_admin", "member"):
        return
    raise HTTPException(403, "You cannot manage this user.")


def _org_by_slug(db: Session, slug: Optional[str]) -> Optional[Org]:
    if not slug:
        return None
    org = db.scalar(select(Org).where(Org.slug == slug))
    if org is None:
        raise HTTPException(404, f"Organisation {slug!r} not found.")
    return org


def user_row(u: User) -> dict[str, Any]:
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role, "persona": u.persona,
        "org": org_brief(u.org), "is_active": u.is_active, "must_change_password": u.must_change_password,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


# --- users --------------------------------------------------------------------

class UserCreate(BaseModel):
    email: EmailStr
    name: str = ""
    role: str = "member"
    org_slug: Optional[str] = None
    persona: str = "QA"
    password: Optional[str] = None  # omit → an invite link is returned instead


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    org_slug: Optional[str] = None
    persona: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
def list_users(org: Optional[str] = None, q: str = "", actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc())
    if actor.role == "org_admin":
        stmt = stmt.where(User.org_id == actor.org_id)
    elif org:
        o = _org_by_slug(db, org)
        stmt = stmt.where(User.org_id == o.id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(User.email).like(like) | func.lower(User.name).like(like))
    return {"users": [user_row(u) for u in db.scalars(stmt)], "assignable_roles": list(_assignable_roles(actor)), "personas": list(PERSONAS)}


def _make_invite(db: Session, actor: User, email: str, name: str, role: str, org_id: Optional[int]) -> tuple[Invite, str]:
    tok, h = new_token()
    inv = Invite(token_hash=h, email=email, name=name, role=role, org_id=org_id, created_by=actor.id,
                 expires_at=utcnow() + timedelta(days=7))
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv, f"{settings.app_base_url.rstrip('/')}/invite/{tok}"


@router.post("/users")
def create_user(body: UserCreate, request: Request, actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    org = _org_by_slug(db, body.org_slug) if body.org_slug else (actor.org if actor.role == "org_admin" else None)
    org_id = org.id if org else None
    _check_target(actor, body.role, org_id)
    if body.persona not in PERSONAS:
        raise HTTPException(400, "Unknown persona.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email already exists.")
    if not body.password:
        inv, link = _make_invite(db, actor, email, body.name, body.role, org_id)
        audit(db, "invite.created", actor=actor, target_type="invite", target_id=inv.id, detail={"email": email, "role": body.role, "org": org.slug if org else None}, request=request)
        return {"invite": {"id": inv.id, "email": email, "link": link, "expires_at": inv.expires_at.isoformat()}}
    validate_password(body.password)
    u = User(email=email, name=body.name.strip(), role=body.role, org_id=org_id, persona=body.persona,
             password_hash=hash_password(body.password), must_change_password=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    audit(db, "user.created", actor=actor, target_type="user", target_id=u.id, detail={"email": email, "role": u.role, "org": org.slug if org else None}, request=request)
    return {"user": user_row(u)}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    _check_can_edit(actor, u)
    changes: dict[str, Any] = {}
    new_role = body.role or u.role
    new_org_id = u.org_id
    if body.org_slug is not None:
        new_org_id = _org_by_slug(db, body.org_slug).id if body.org_slug else None
    if body.role is not None or body.org_slug is not None:
        if u.id == actor.id and new_role != u.role:
            raise HTTPException(400, "You cannot change your own role.")
        _check_target(actor, new_role, new_org_id)
        if new_role != u.role:
            changes["role"] = [u.role, new_role]
        if new_org_id != u.org_id:
            changes["org_id"] = [u.org_id, new_org_id]
        u.role, u.org_id = new_role, new_org_id
    if body.name is not None:
        u.name = body.name.strip()
    if body.persona is not None:
        if body.persona not in PERSONAS:
            raise HTTPException(400, "Unknown persona.")
        u.persona = body.persona
    if body.is_active is not None and body.is_active != u.is_active:
        if u.id == actor.id:
            raise HTTPException(400, "You cannot deactivate yourself.")
        u.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            for s in db.scalars(select(UserSession).where(UserSession.user_id == u.id)):
                db.delete(s)
    db.commit()
    db.refresh(u)
    audit(db, "user.updated", actor=actor, target_type="user", target_id=u.id, detail=changes, request=request)
    return {"user": user_row(u)}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    _check_can_edit(actor, u)
    temp = secrets.token_urlsafe(9)
    u.password_hash = hash_password(temp)
    u.must_change_password = True
    for s in db.scalars(select(UserSession).where(UserSession.user_id == u.id)):
        db.delete(s)
    db.commit()
    audit(db, "user.password_reset", actor=actor, target_type="user", target_id=u.id, request=request)
    return {"temporary_password": temp}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: int, request: Request, actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    _check_can_edit(actor, u)
    n = 0
    for s in db.scalars(select(UserSession).where(UserSession.user_id == u.id)):
        db.delete(s)
        n += 1
    db.commit()
    audit(db, "user.sessions_revoked", actor=actor, target_type="user", target_id=u.id, detail={"count": n}, request=request)
    return {"revoked": n}


# --- invites ------------------------------------------------------------------

@router.get("/invites")
def list_invites(actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    stmt = select(Invite).where(Invite.used_at.is_(None)).order_by(Invite.created_at.desc())
    if actor.role == "org_admin":
        stmt = stmt.where(Invite.org_id == actor.org_id)
    now = utcnow()
    rows = []
    for i in db.scalars(stmt):
        org = db.get(Org, i.org_id) if i.org_id else None
        rows.append({"id": i.id, "email": i.email, "name": i.name, "role": i.role, "org": org_brief(org),
                     "expires_at": i.expires_at.isoformat(), "expired": _aware(i.expires_at) < now})
    return {"invites": rows}


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: int, request: Request, actor: User = Depends(_require_manager), db: Session = Depends(get_db)):
    inv = db.get(Invite, invite_id)
    if inv is None or (actor.role == "org_admin" and inv.org_id != actor.org_id):
        raise HTTPException(404, "Invite not found.")
    db.delete(inv)
    db.commit()
    audit(db, "invite.revoked", actor=actor, target_type="invite", target_id=invite_id, request=request)
    return {"ok": True}


# --- organisations (platform only) ------------------------------------------------

class OrgBody(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: Optional[str] = None
    city: str = ""
    country: str = "India"
    ontology_keys: list[str] = []
    plant_ids: list[str] = []
    notes: str = ""
    is_active: bool = True


class OrgPatch(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    ontology_keys: Optional[list[str]] = None
    plant_ids: Optional[list[str]] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80] or "org"


def _validate_links(ontology_keys: list[str], plant_ids: list[str]) -> None:
    df = data.frame()
    known = set(df["Mfg_Ontology_Key"].dropna().unique()) if not df.empty else set()
    bad = [k for k in ontology_keys if known and k not in known]
    if bad:
        raise HTTPException(400, f"Unknown manufacturer keys: {', '.join(bad)}")
    plants = data.cdmo()["plants"]
    badp = [p for p in plant_ids if p not in plants]
    if badp:
        raise HTTPException(400, f"Unknown plants: {', '.join(badp)}")


def _org_stats(db: Session, org: Org) -> dict[str, Any]:
    users = db.scalar(select(func.count()).select_from(User).where(User.org_id == org.id)) or 0
    df = data.org_frame(org.ontology_keys or [])
    return {"users": int(users), "alerts": int(len(df)), "plants": len(org.plant_ids or [])}


@router.get("/orgs")
def list_orgs(actor: User = Depends(require_platform), db: Session = Depends(get_db)):
    orgs = db.scalars(select(Org).order_by(Org.name)).all()
    return {"orgs": [{**org_payload(o), "stats": _org_stats(db, o)} for o in orgs]}


@router.post("/orgs")
def create_org(body: OrgBody, request: Request, actor: User = Depends(require_platform), db: Session = Depends(get_db)):
    slug = _slugify(body.slug or body.name)
    if db.scalar(select(Org).where(Org.slug == slug)):
        raise HTTPException(409, f"An organisation with slug {slug!r} already exists.")
    _validate_links(body.ontology_keys, body.plant_ids)
    org = Org(slug=slug, name=body.name.strip(), city=body.city, country=body.country,
              ontology_keys=sorted(set(body.ontology_keys)), plant_ids=list(dict.fromkeys(body.plant_ids)),
              notes=body.notes, is_active=body.is_active)
    db.add(org)
    db.commit()
    db.refresh(org)
    audit(db, "org.created", actor=actor, target_type="org", target_id=org.slug, detail=body.model_dump(), request=request)
    return {"org": {**org_payload(org), "stats": _org_stats(db, org)}}


@router.patch("/orgs/{slug}")
def update_org(slug: str, body: OrgPatch, request: Request, actor: User = Depends(require_platform), db: Session = Depends(get_db)):
    org = _org_by_slug(db, slug)
    patch = body.model_dump(exclude_none=True)
    _validate_links(patch.get("ontology_keys", []), patch.get("plant_ids", []))
    for k, v in patch.items():
        if k == "ontology_keys":
            v = sorted(set(v))
        if k == "plant_ids":
            v = list(dict.fromkeys(v))
        setattr(org, k, v)
    db.commit()
    db.refresh(org)
    audit(db, "org.updated", actor=actor, target_type="org", target_id=org.slug, detail=patch, request=request)
    return {"org": {**org_payload(org), "stats": _org_stats(db, org)}}


@router.get("/manufacturers")
def manufacturers(q: str = "", limit: int = Query(20, le=100), actor: User = Depends(require_platform)):
    return {"manufacturers": insights.manufacturer_search(q, limit)}


@router.get("/plants")
def all_plants(actor: User = Depends(require_platform), db: Session = Depends(get_db)):
    owners: dict[str, int] = {}
    for o in db.scalars(select(Org)):
        for p in o.plant_ids or []:
            owners.setdefault(p, o.id)
    custom = {p.asset_id for p in db.scalars(select(Plant))}
    orgs = {o.id: o.slug for o in db.scalars(select(Org))}
    return {"plants": [
        {"asset_id": p.asset_id, "name": p.site_name, "city": p.city, "state": p.state,
         "certifications": p.certifications_active, "containment_class": p.containment_class,
         "capabilities": len(p.capabilities), "custom": p.asset_id in custom,
         "org": orgs.get(owners.get(p.asset_id)) if p.asset_id in owners else None}
        for p in data.cdmo()["plants"].values()
    ]}


# --- audit + overview -----------------------------------------------------------------

@router.get("/audit")
def audit_log(page: int = Query(1, ge=1), size: int = Query(50, le=200), action: str = "",
              actor: User = Depends(require_platform), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.at.desc()).offset((page - 1) * size).limit(size))
    return {"total": total, "page": page, "size": size, "items": [
        {"id": a.id, "at": a.at.isoformat(), "actor": a.actor_email, "action": a.action,
         "target": f"{a.target_type}:{a.target_id}" if a.target_type else "", "detail": a.detail, "ip": a.ip}
        for a in rows
    ]}


@router.get("/overview")
def admin_overview(actor: User = Depends(require_platform), db: Session = Depends(get_db)):
    now = utcnow()
    week = now - timedelta(days=7)
    users_total = db.scalar(select(func.count()).select_from(User)) or 0
    active_7d = db.scalar(select(func.count()).select_from(User).where(User.last_login_at >= week)) or 0
    logins_7d = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.login", AuditLog.at >= week)) or 0
    failed_7d = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.login_failed", AuditLog.at >= week)) or 0
    orgs = db.scalars(select(Org).order_by(Org.name)).all()
    jobs = db.scalars(select(JobRun).order_by(JobRun.created_at.desc()).limit(8)).all()
    summary = insights.platform_summary()
    return {
        "users": {"total": int(users_total), "active_7d": int(active_7d), "logins_7d": int(logins_7d), "failed_logins_7d": int(failed_7d)},
        "orgs": [{**org_payload(o), "stats": _org_stats(db, o)} for o in orgs],
        "data": data.data_status(),
        "nsq": {"kpis": summary["kpis"], "trend": summary["trend"], "latest_alerts": summary["latest_alerts"][:8],
                "top_manufacturers": summary["top_manufacturers"][:8]},
        "recent_jobs": [
            {"id": j.id, "job_key": j.job_key, "status": j.status, "by": j.started_by_email,
             "created_at": j.created_at.isoformat(), "finished_at": j.finished_at.isoformat() if j.finished_at else None,
             "exit_code": j.exit_code}
            for j in jobs
        ],
    }
