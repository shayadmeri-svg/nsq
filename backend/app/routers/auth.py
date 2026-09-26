"""Sign-in, sign-out, current user, password change, invite acceptance."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import SESSION_COOKIE
from ..db import get_db
from ..models import Invite, Org, PLATFORM_ROLES, User, UserSession, utcnow
from ..security import (
    _aware,
    check_throttle,
    clear_failures,
    clear_session_cookie,
    client_ip,
    create_session,
    current_user,
    hash_password,
    record_failure,
    session_user,
    set_session_cookie,
    token_hash,
    validate_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class AcceptInviteBody(BaseModel):
    token: str
    name: str = ""
    password: str


def org_brief(org: Optional[Org]) -> Optional[dict[str, Any]]:
    if org is None:
        return None
    return {"id": org.id, "slug": org.slug, "name": org.name, "city": org.city, "country": org.country}


def user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "persona": user.persona,
        "org": org_brief(user.org),
        "must_change_password": user.must_change_password,
        "is_platform": user.role in PLATFORM_ROLES,
        "permissions": {
            "admin": user.role in PLATFORM_ROLES,
            "manage_users": user.role in PLATFORM_ROLES or user.role == "org_admin",
            "run_jobs": user.role in PLATFORM_ROLES,
            "run_destructive_jobs": user.role == "super_admin",
            "platform_analytics": user.role in PLATFORM_ROLES,
        },
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip = client_ip(request)
    check_throttle(f"e:{email}", f"i:{ip}")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        record_failure(f"e:{email}", f"i:{ip}")
        audit(db, "auth.login_failed", actor_email=email, request=request)
        raise HTTPException(401, "Email or password is incorrect.")
    if user.org is not None and not user.org.is_active and user.role not in PLATFORM_ROLES:
        raise HTTPException(403, "Your organisation's access is disabled.")
    clear_failures(f"e:{email}")
    token = create_session(db, user, request)
    set_session_cookie(response, token)
    audit(db, "auth.login", actor=user, request=request)
    return {"user": user_payload(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        sess = db.get(UserSession, token_hash(tok))
        if sess:
            db.delete(sess)
            db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": user_payload(user)}


@router.get("/check", include_in_schema=False)
def check(request: Request, db: Session = Depends(get_db)):
    """nginx auth_request target: 204 when signed in, 401 otherwise."""
    found = session_user(db, request.cookies.get(SESSION_COOKIE))
    if not found:
        raise HTTPException(401)
    return Response(status_code=204)


@router.post("/change-password")
def change_password(body: ChangePasswordBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    validate_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # Sign out every other session.
    current = token_hash(request.cookies.get(SESSION_COOKIE, ""))
    for s in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.id != current)):
        db.delete(s)
    db.commit()
    audit(db, "auth.password_changed", actor=user, target_type="user", target_id=user.id, request=request)
    return {"ok": True}


def _open_invite(db: Session, token: str) -> Invite:
    inv = db.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if inv is None or inv.used_at is not None or _aware(inv.expires_at) < utcnow():
        raise HTTPException(404, "This invite link is invalid or has expired.")
    return inv


@router.get("/invite/{token}")
def invite_info(token: str, db: Session = Depends(get_db)):
    inv = _open_invite(db, token)
    org = db.get(Org, inv.org_id) if inv.org_id else None
    return {"email": inv.email, "name": inv.name, "role": inv.role, "org": org_brief(org)}


@router.post("/accept-invite")
def accept_invite(body: AcceptInviteBody, request: Request, response: Response, db: Session = Depends(get_db)):
    inv = _open_invite(db, body.token)
    validate_password(body.password)
    if db.scalar(select(User).where(User.email == inv.email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(
        email=inv.email, name=(body.name or inv.name).strip(), password_hash=hash_password(body.password),
        role=inv.role, org_id=inv.org_id,
    )
    db.add(user)
    inv.used_at = utcnow()
    db.commit()
    db.refresh(user)
    audit(db, "auth.invite_accepted", actor=user, target_type="user", target_id=user.id, request=request)
    token = create_session(db, user, request)
    set_session_cookie(response, token)
    return {"user": user_payload(user)}
