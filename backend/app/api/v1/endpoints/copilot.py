from uuid import uuid4

from fastapi import APIRouter

from app.schemas.copilot import (
    CopilotChatRequest,
    CopilotChatResponse,
    CopilotExecuteRequest,
    CopilotExecuteResponse,
)
from app.services.orchestration.runtime import copilot_runtime

router = APIRouter()


@router.post("/chat", response_model=CopilotChatResponse)
async def chat_with_copilot(payload: CopilotChatRequest) -> CopilotChatResponse:
    session_id = payload.session_id or str(uuid4())
    result = await copilot_runtime.respond(session_id, payload.message, requested_module=payload.module)
    return CopilotChatResponse(
        answer=result["answer"],
        sources=[],
        status="success",
        module=result["module"],
        recommended_actions=result["recommended_actions"],
    )


@router.post("/execute", response_model=CopilotExecuteResponse)
async def execute_with_copilot(payload: CopilotExecuteRequest) -> CopilotExecuteResponse:
    session_id = payload.session_id or str(uuid4())
    result = await copilot_runtime.execute(
        session_id,
        payload.message,
        requested_module=payload.module,
        confirm=payload.confirm,
        context=payload.context,
    )
    return CopilotExecuteResponse(
        status=result["status"],
        module=result["module"],
        action_type=result["action_type"],
        answer=result["answer"],
        execution_plan=result["execution_plan"],
        result=result["result"],
    )
