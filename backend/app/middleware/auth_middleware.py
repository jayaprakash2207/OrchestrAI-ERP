from __future__ import annotations

from typing import Callable

from fastapi import Request
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import settings


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"} or request.url.path.startswith("/api/v1/health"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            if settings.environment != "production":
                request.state.user = {"sub": "development-user", "mode": "development"}
                return await call_next(request)
            return JSONResponse(status_code=401, content={"error_code": "authentication_error", "message": "Missing JWT token", "details": {}})
        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm])
            request.state.user = payload
        except JWTError:
            return JSONResponse(status_code=401, content={"error_code": "authentication_error", "message": "Invalid JWT token", "details": {}})
        return await call_next(request)
