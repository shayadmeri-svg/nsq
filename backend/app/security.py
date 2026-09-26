"""Passwords, session tokens, login throttling, request guards."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import CLIENT_HEADER, MIN_PASSWORD_LENGTH, SESSION_COOKIE, settings
from .db import get_db
from .models import Org, PLATFORM_ROLES, User, UserSession, utcnow

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerificationError, InvalidHashError):
        return False


def validate_password(pw: str) -> None:
    if len(pw or "") < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def new_token() -> tuple[str, str]:
    """Return (token for the client, sha256 for the database)."""
    tok = secrets.token_urlsafe(32)
    return tok, token_hash(tok)


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


# --- login throttling (per email and per IP, in-process) --------------------
_FAIL_WINDOW_S = 15 * 60
_FAIL_LIMIT = 8
_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()


def _prune(key: str, now: float) -> list[float]:
    arr = [t for t in _fails.get(key, []) if now - t < _FAIL_WINDOW_S]
    _fails[key] = arr
    return arr


def check_throttle(*keys: str) -> None:
    now = time.time()
    with _fails_lock:
        for k in keys:
            if len(_prune(k, now)) >= _FAIL_LIMIT:
                raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")


def record_failure(*keys: str) -> None:
    now = time.time()
    with _fails_lock:
        for k in keys:
            _prune(k, now).append(now)


def clear_failures(*keys: str) -> None:
    with _fails_lock:
        for k in keys:
            _fails.pop(k, None)


# --- sessions -----------------------------------------------------------------

def create_session(db: Session, user: User, request: Request) -> str:
    tok, h = new_token()
    now = utcnow()
    db.add(UserSession(
        id=h, user_id=user.id, created_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        ip=client_ip(request)[:64], user_agent=(request.headers.get("user-agent") or "")[:300],
    ))
    user.last_login_at = now
    db.commit()
    return tok


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="lax",
        max_age=settings.session_ttl_hours * 3600, path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def session_user(db: Session, token: Optional[str]) -> Optional[tuple[User, UserSession]]:
    if not token:
        return None
    sess = db.get(UserSession, token_hash(token))
    if sess is None:
        return None
    now = utcnow()
    if _aware(sess.expires_at) <= now:
        db.delete(sess)
        db.commit()
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    # Sliding expiry, written at most once a minute.
    if (now - _aware(sess.last_seen_at)).total_seconds() > 60:
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(hours=settings.session_ttl_hours)
        db.commit()
    return user, sess


# --- dependencies -------------------------------------------------------------

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    found = session_user(db, request.cookies.get(SESSION_COOKIE))
    if not found:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    user, _ = found
    request.state.user = user
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this.")
        return user
    return dep


require_platform = require_roles(*PLATFORM_ROLES)
require_super = require_roles("super_admin")


def can_access_org(user: User, org: Org) -> bool:
    return user.role in PLATFORM_ROLES or (user.org_id is not None and user.org_id == org.id)


def can_manage_org(user: User, org: Org) -> bool:
    return user.role in PLATFORM_ROLES or (user.role == "org_admin" and user.org_id == org.id)


def org_for_user(db: Session, slug: str, user: User) -> Org:
    org = db.scalar(select(Org).where(Org.slug == slug))
    if org is None or not can_access_org(user, org):
        # Same answer for "missing" and "not yours" so slugs can't be probed.
        raise HTTPException(404, "Organisation not found.")
    if not org.is_active and user.role not in PLATFORM_ROLES:
        raise HTTPException(403, "This organisation is disabled.")
    return org


async def csrf_guard(request: Request) -> None:
    """Mutating requests must carry the client header. Cross-site forms can't
    set custom headers, and a cross-site fetch that does triggers a CORS
    preflight we don't allow — so this plus SameSite=Lax blocks CSRF."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.headers.get(CLIENT_HEADER):
        raise HTTPException(403, "Missing client header.")
