import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger("app.middleware")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error path=%s method=%s request_id=%s client=%s",
                request.url.path,
                request.method,
                getattr(request.state, "request_id", "unknown"),
                request.client.host if request.client else "unknown",
            )
            raise


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        request.state.started_at = time.time()
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        response.headers["X-Process-Time"] = f"{process_time:.6f}"

        user_id = request.headers.get("X-User-ID", "anonymous")
        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            "request_completed timestamp=%s request_id=%s user=%s ip=%s method=%s path=%s status=%s duration_ms=%.2f",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(getattr(request.state, "started_at", time.time()))),
            getattr(request.state, "request_id", "unknown"),
            user_id,
            client_ip,
            request.method,
            request.url.path,
            response.status_code,
            process_time * 1000,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - 60

        with self.lock:
            window = self.requests[client_ip]
            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= settings.rate_limit_requests_per_minute:
                logger.warning(
                    "rate_limit_exceeded request_id=%s ip=%s path=%s",
                    getattr(request.state, "request_id", "unknown"),
                    client_ip,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "rate_limit_exceeded",
                        "message": "Too many requests. Please retry later.",
                        "details": {
                            "request_id": getattr(request.state, "request_id", "unknown"),
                            "limit_per_minute": settings.rate_limit_requests_per_minute,
                        },
                    },
                )
            window.append(now)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests_per_minute)
        return response
