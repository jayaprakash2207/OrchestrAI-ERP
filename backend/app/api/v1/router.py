from fastapi import APIRouter

from app.api.v1.endpoints import autoerp, copilot, finance, health, masters, supply_chain

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(autoerp.router, prefix="/autoerp", tags=["autoerp"])
api_router.include_router(copilot.router, prefix="/copilot", tags=["copilot"])
api_router.include_router(finance.router)
api_router.include_router(supply_chain.router)
api_router.include_router(masters.router)
