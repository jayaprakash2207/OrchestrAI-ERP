from fastapi import APIRouter

from app.services.health import collect_system_health

router = APIRouter()


@router.get("/")
async def readiness():
    return await collect_system_health()
