from pydantic import BaseModel, Field


class AutoERPRequest(BaseModel):
    company_name: str | None = None
    requirements: str = Field(..., min_length=10)


class AutoERPResponse(BaseModel):
    generation_id: str | None = None
    summary: str
    modules: list[str]
    status: str


class AutoERPStatusResponse(BaseModel):
    generation_id: str
    status: str
    current_step: int
    error: str | None = None
    available_files: list[str] = Field(default_factory=list)
