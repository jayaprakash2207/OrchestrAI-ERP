from typing import Any

from pydantic import BaseModel, Field


class CopilotChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    module: str | None = None


class CopilotChatResponse(BaseModel):
    answer: str
    sources: list[str]
    status: str
    module: str | None = None
    recommended_actions: list[str] = []


class CopilotExecuteRequest(BaseModel):
    message: str = Field(..., min_length=3)
    module: str | None = None
    session_id: str | None = None
    confirm: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class CopilotExecutionPlanResponse(BaseModel):
    action_type: str
    module: str
    target_system: str = "jd_edwards"
    requires_confirmation: bool = True
    parsed_payload: dict[str, Any] = Field(default_factory=dict)
    summary: str


class CopilotExecuteResponse(BaseModel):
    status: str
    module: str
    action_type: str | None = None
    answer: str
    execution_plan: CopilotExecutionPlanResponse | None = None
    result: dict[str, Any] | None = None
