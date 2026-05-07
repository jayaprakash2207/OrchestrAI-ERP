from fastapi import APIRouter

from app.schemas.health import HealthResponse
from app.services.health import collect_system_health, collect_system_metrics

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return await collect_system_health()


@router.get("/metrics")
async def metrics() -> dict:
    return await collect_system_metrics()
