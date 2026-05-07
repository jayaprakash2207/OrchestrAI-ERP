from pydantic import BaseModel, Field


class ServiceHealthStatus(BaseModel):
    status: str
    details: dict[str, str] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    api: ServiceHealthStatus
    database: ServiceHealthStatus
    llm: ServiceHealthStatus
    chromadb: ServiceHealthStatus
    jde: ServiceHealthStatus | None = None
    redis: ServiceHealthStatus | None = None
