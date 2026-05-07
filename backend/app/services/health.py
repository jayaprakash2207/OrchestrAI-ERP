import logging

import httpx
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import db_manager
from app.integrations.jde_connector import JDEConnectorFactory, JDEConnectorError
from app.schemas.health import HealthResponse, ServiceHealthStatus

logger = logging.getLogger("app.health")


async def _check_database() -> ServiceHealthStatus:
    try:
        db_manager.initialize()
        with db_manager.session_scope() as session:
            session.execute(text("SELECT 1"))
        return ServiceHealthStatus(status="healthy", details={"message": "PostgreSQL reachable"})
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", exc.__class__.__name__)
        return ServiceHealthStatus(status="unhealthy", details={"message": "PostgreSQL unavailable"})


async def _check_chromadb() -> ServiceHealthStatus:
    base_url = f"http://{settings.chroma_host}:{settings.chroma_port}"
    async with httpx.AsyncClient(timeout=settings.chroma_healthcheck_timeout_seconds) as client:
        for path in ("/api/v1/heartbeat", "/api/v2/heartbeat"):
            try:
                response = await client.get(f"{base_url}{path}")
                response.raise_for_status()
                return ServiceHealthStatus(status="healthy", details={"message": "ChromaDB reachable"})
            except httpx.HTTPError:
                continue
    return ServiceHealthStatus(status="degraded", details={"message": "ChromaDB heartbeat unavailable"})


async def _check_llm() -> ServiceHealthStatus:
    if not settings.gemini_api_key.get_secret_value():
        return ServiceHealthStatus(status="unhealthy", details={"message": "Gemini API key missing"})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}"
    params = {"key": settings.gemini_api_key.get_secret_value()}
    try:
        async with httpx.AsyncClient(timeout=settings.gemini_healthcheck_timeout_seconds) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
        return ServiceHealthStatus(status="healthy", details={"message": f"Gemini model {settings.gemini_model} reachable"})
    except httpx.HTTPError:
        logger.warning("Gemini API health check failed for model=%s", settings.gemini_model)
        return ServiceHealthStatus(status="degraded", details={"message": "Gemini API unreachable"})


async def _check_redis() -> ServiceHealthStatus | None:
    if not settings.redis_enabled:
        return None

    try:
        client = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        client.ping()
        client.close()
        return ServiceHealthStatus(status="healthy", details={"message": "Redis reachable"})
    except RedisError:
        logger.warning("Redis health check failed")
        return ServiceHealthStatus(status="degraded", details={"message": "Redis unavailable"})


async def _check_jde() -> ServiceHealthStatus:
    try:
        connector = JDEConnectorFactory.create()
        connector.get_currencies()
        return ServiceHealthStatus(status="healthy", details={"message": "JD Edwards connector reachable"})
    except JDEConnectorError:
        logger.warning("JD Edwards connector health check failed")
        return ServiceHealthStatus(status="degraded", details={"message": "JD Edwards connector unavailable"})
    except Exception:
        logger.warning("JD Edwards health check failed unexpectedly")
        return ServiceHealthStatus(status="degraded", details={"message": "JD Edwards health check failed"})


async def collect_system_health() -> HealthResponse:
    database = await _check_database()
    chromadb = await _check_chromadb()
    llm = await _check_llm()
    redis_status = await _check_redis()
    jde_status = await _check_jde()
    api = ServiceHealthStatus(status="healthy", details={"message": "API operational"})

    statuses = [api.status, database.status, chromadb.status, llm.status, jde_status.status]
    if redis_status:
        statuses.append(redis_status.status)

    overall = "healthy"
    if "unhealthy" in statuses:
        overall = "unhealthy"
    elif "degraded" in statuses:
        overall = "degraded"

    return HealthResponse(
        status=overall,
        api=api,
        database=database,
        llm=llm,
        chromadb=chromadb,
        jde=jde_status,
        redis=redis_status,
    )


async def collect_system_metrics() -> dict:
    db_manager.initialize()
    pool = db_manager._engine.pool if db_manager._engine is not None else None
    return {
        "requests": {"rate_limit_per_minute": settings.rate_limit_requests_per_minute},
        "llm": {
            "model": settings.gemini_model,
            "daily_token_budget": settings.gemini_daily_token_budget,
            "monthly_token_budget": settings.gemini_monthly_token_budget,
        },
        "database": {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_class": pool.__class__.__name__ if pool else None,
        },
        "components": {
            "redis_enabled": settings.redis_enabled,
            "jde_mode": settings.jde_connection_mode,
            "chroma_collection": settings.chroma_jde_collection_name,
        },
    }
