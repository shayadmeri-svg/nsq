"""Append-only audit trail."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User
from .security import client_ip


def audit(
    db: Session,
    action: str,
    actor: Optional[User] = None,
    target_type: str = "",
    target_id: Any = "",
    detail: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
    actor_email: str = "",
    commit: bool = True,
) -> None:
    db.add(AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=(actor.email if actor else actor_email)[:254],
        action=action,
        target_type=target_type,
        target_id=str(target_id)[:120],
        detail=detail or {},
        ip=client_ip(request)[:64] if request else "",
    ))
    if commit:
        db.commit()
