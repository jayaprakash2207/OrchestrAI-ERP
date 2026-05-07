from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedDocument(BaseModel):
    document_id: str
    content: str
    source: str
    category: str
    version: str | None = None
    relevance_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Requirement(BaseModel):
    type: Literal[
        "ACCOUNTING_STRUCTURE",
        "APPROVAL_WORKFLOW",
        "CURRENCY",
        "DIMENSION",
        "REPORT",
        "INTEGRATION",
        "COMPLIANCE",
    ]
    description: str
    priority: int = Field(..., ge=1, le=5)
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class JDECopilotState(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    current_module: Literal["finance", "supply_chain", "manufacturing", "sales", "hr"] = "finance"
    query_id: str = Field(default_factory=lambda: str(uuid4()))
    context: dict[str, Any] = Field(default_factory=dict)
    retrieved_knowledge: list[RetrievedDocument] = Field(default_factory=list)
    decision: Literal["query", "action"] | None = None
    action_type: str | None = None
    execution_needed: bool = False
    approval_required: bool = False
    error_message: str | None = None


class AutoERPGeneratorState(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    generation_id: str = Field(default_factory=lambda: str(uuid4()))
    company_name: str = ""
    requirements_input: str = ""
    parsed_requirements: list[Requirement] = Field(default_factory=list)
    schema_design: dict[str, Any] = Field(default_factory=dict)
    generated_code: dict[str, Any] = Field(default_factory=dict)
    generated_configs: dict[str, Any] = Field(default_factory=dict)
    master_data: dict[str, Any] = Field(default_factory=dict)
    current_step: int = 1
    error: str | None = None


class RouteDecision(BaseModel):
    agent: str
    next_step: str
    metadata: dict[str, Any] = Field(default_factory=dict)
