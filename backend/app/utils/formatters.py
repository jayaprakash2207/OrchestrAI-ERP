from __future__ import annotations

from datetime import datetime, timezone


def error_response(error_code: str, message: str, details: dict | None = None, request_id: str | None = None) -> dict:
    return {
        "error_code": error_code,
        "message": message,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id or "unknown",
    }
