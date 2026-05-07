from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel, Generic[T]):
    total: int = Field(..., ge=0, examples=[125])
    page: int = Field(..., ge=1, examples=[1])
    page_size: int = Field(..., ge=1, le=500, examples=[25])
    items: list[T]

    model_config = ConfigDict(json_schema_extra={"example": {"total": 2, "page": 1, "page_size": 25, "items": []}})


class ErrorResponse(BaseModel):
    error_code: str = Field(..., examples=["validation_error"])
    message: str = Field(..., examples=["Request validation failed."])
    details: dict | None = Field(default=None, examples=[{"field": "amount", "issue": "must be greater than zero"}])
    timestamp: datetime = Field(..., examples=["2026-04-06T12:00:00Z"])
    request_id: str = Field(..., examples=["2ef67f0a-e3b7-4c0c-bced-c2af3a2b4fb2"])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error_code": "validation_error",
                "message": "Request validation failed.",
                "details": {"field": "amount", "issue": "must be greater than zero"},
                "timestamp": "2026-04-06T12:00:00Z",
                "request_id": "2ef67f0a-e3b7-4c0c-bced-c2af3a2b4fb2",
            }
        }
    )
