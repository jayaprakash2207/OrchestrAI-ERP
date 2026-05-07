from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.financial import AuditLog
from app.models.enums import AuditAction


def _normalize_payload(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    return json.loads(json.dumps(payload, default=str))


def create_audit_entry(
    db: Session,
    *,
    table_name: str,
    record_id: UUID,
    action: AuditAction,
    request: Request | None = None,
    user_id: str | None = None,
    before_values: dict | None = None,
    after_values: dict | None = None,
) -> AuditLog:
    resolved_user = user_id or (request.headers.get("X-User-ID") if request else None)
    audit = AuditLog(
        table_name=table_name,
        record_id=record_id,
        action=action,
        user_id=resolved_user,
        timestamp=datetime.now(timezone.utc),
        before_values=_normalize_payload(before_values),
        after_values=_normalize_payload(after_values),
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(audit)
    return audit
