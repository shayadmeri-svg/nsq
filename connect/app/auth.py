"""Who is calling. People: their platform session, checked with the main API (/api/auth/me), cached briefly.
Edge agents: a per-agent token (only its SHA-256 is stored)."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Optional

import httpx
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Agent, Plant, utcnow

API_URL = os.environ.get("API_URL", "http://api:8001")
SESSION_COOKIE = "nsq_session"
FEATURE = "monitor"
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def current_user(request: Request) -> dict[str, Any]:
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(401, "Sign in first.")
    hit = _cache.get(cookie)
    if hit and time.monotonic() - hit[0] < 30:
        user = hit[1]
    else:
        try:
            r = httpx.get(f"{API_URL}/api/auth/me", cookies={SESSION_COOKIE: cookie}, timeout=10)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Platform sign-in service unreachable.") from exc
        if r.status_code != 200:
            raise HTTPException(401, "Sign in first.")
        user = r.json()["user"]
        _cache[cookie] = (time.monotonic(), user)
        if len(_cache) > 500:
            _cache.clear()
    if not user.get("is_platform") and FEATURE not in (user.get("features") or []):
        raise HTTPException(403, "Your access doesn't include Plant monitor. Ask your organisation admin.")
    return user


def csrf(request: Request) -> None:
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.headers.get("x-nsq-client"):
        raise HTTPException(403, "Missing client header.")


def plant_for(db: Session, plant_id: int, user: dict[str, Any]) -> Plant:
    p = db.get(Plant, plant_id)
    if p is None or not (user.get("is_platform") or (user.get("org") or {}).get("slug") == p.org_slug):
        raise HTTPException(404, "Plant not found.")  # same answer for missing and not yours
    return p


def current_agent(authorization: str = Header(""), db: Session = Depends(get_db)) -> Agent:
    tok = authorization.removeprefix("Bearer ").strip()
    a = db.scalar(select(Agent).where(Agent.token_hash == token_hash(tok))) if tok else None
    if a is None:
        raise HTTPException(401, "Unknown or revoked agent token.")
    a.last_seen_at = utcnow()
    db.commit()
    return a


def visible_plants(user: dict[str, Any]) -> Optional[str]:
    """None = every plant (platform staff), else the user's organisation slug."""
    return None if user.get("is_platform") else (user.get("org") or {}).get("slug") or "__none__"
