import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError, AuthenticationError, AuthorizationError, ResourceNotFoundError

logger = logging.getLogger("app.errors")


def _error_payload(request: Request, error_code: str, message: str, details: dict | None = None) -> dict:
    payload = {
        "error_code": error_code,
        "message": message,
        "details": details or {},
    }
    payload["details"]["request_id"] = getattr(request.state, "request_id", "unknown")
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=_error_payload(request, exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=_error_payload(request, exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(ResourceNotFoundError)
    async def not_found_error_handler(request: Request, exc: ResourceNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_error_payload(request, exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code_map = {
            401: "authentication_error",
            403: "authorization_error",
            404: "not_found",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                request,
                code_map.get(exc.status_code, "http_error"),
                str(exc.detail),
                {"status_code": exc.status_code},
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                request,
                "validation_error",
                "Request validation failed.",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Internal server error path=%s method=%s request_id=%s",
            request.url.path,
            request.method,
            getattr(request.state, "request_id", "unknown"),
        )
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request,
                "internal_server_error",
                "An unexpected server error occurred.",
                {},
            ),
        )
