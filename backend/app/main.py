from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.middleware import ErrorTrackingMiddleware, RateLimitMiddleware, RequestIDMiddleware, RequestMetricsMiddleware
from app.db.session import db_manager
from app.middleware.auth_middleware import AuthMiddleware
from app.schemas.health import HealthResponse
from app.services.health import collect_system_health, collect_system_metrics
from app.services.realtime import websocket_hub


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.project_name,
        description="AI-powered ERP platform for ERP generation and JD Edwards copiloting.",
        version="0.1.0",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(RequestMetricsMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Limit"],
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(api_router, prefix="/api")

    @app.on_event("startup")
    async def on_startup() -> None:
        settings.validate_runtime_requirements()
        settings.log_startup_config()
        if settings.db_startup_check_enabled and settings.environment != "test":
            db_manager.ping()

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        db_manager.shutdown()

    @app.get("/health", tags=["health"], response_model=HealthResponse)
    async def healthcheck() -> HealthResponse:
        return await collect_system_health()

    @app.get("/metrics", tags=["metrics"])
    async def metrics() -> dict:
        return await collect_system_metrics()

    @app.websocket("/ws/chat/{session_id}")
    async def chat_socket(websocket: WebSocket, session_id: str) -> None:
        channel = f"chat:{session_id}"
        await websocket_hub.connect(channel, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await websocket_hub.disconnect(channel, websocket)

    @app.websocket("/ws/generate/{generation_id}")
    async def generate_socket(websocket: WebSocket, generation_id: str) -> None:
        channel = f"generate:{generation_id}"
        await websocket_hub.connect(channel, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await websocket_hub.disconnect(channel, websocket)

    return app


app = create_app()
