import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.schemas.autoerp import AutoERPRequest, AutoERPResponse, AutoERPStatusResponse
from app.services.orchestration.runtime import GENERATION_JOBS, autoerp_runtime
from app.services.orchestration.state import AutoERPGeneratorState

router = APIRouter()


@router.post("/generate", response_model=AutoERPResponse)
async def generate_erp(payload: AutoERPRequest) -> AutoERPResponse:
    state = AutoERPGeneratorState(company_name=payload.company_name or "", requirements_input=payload.requirements)
    GENERATION_JOBS[state.generation_id] = {
        "state": state,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    asyncio.create_task(autoerp_runtime.run_generation(state.generation_id))
    return AutoERPResponse(
        generation_id=state.generation_id,
        summary=f"Started ERP generation for: {payload.requirements}",
        modules=["General Ledger", "Accounts Payable", "Accounts Receivable", "Configuration", "Master Data"],
        status="running",
    )


@router.get("/generate/{generation_id}", response_model=AutoERPStatusResponse)
async def get_generation_status(generation_id: str) -> AutoERPStatusResponse:
    job = GENERATION_JOBS.get(generation_id)
    if not job:
        raise HTTPException(status_code=404, detail="Generation not found")
    state = job["state"]
    available_files = list(state.generated_code) + list(state.generated_configs)
    if state.schema_design:
        available_files.append("schema.json")
    if state.master_data:
        available_files.append("master_data.json")
    return AutoERPStatusResponse(
        generation_id=generation_id,
        status=job["status"],
        current_step=state.current_step,
        error=job.get("error"),
        available_files=available_files,
    )


@router.get("/generate/{generation_id}/download")
async def download_generation(generation_id: str) -> Response:
    job = GENERATION_JOBS.get(generation_id)
    if not job:
        raise HTTPException(status_code=404, detail="Generation not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Generation is not completed yet")
    payload = autoerp_runtime.package_generation(generation_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="autoerp-{generation_id}.zip"'},
    )
