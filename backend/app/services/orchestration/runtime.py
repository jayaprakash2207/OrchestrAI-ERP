from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from app.agents.finance_agent import FinanceAgent
from app.agents.hr_agent import HRAgent
from app.agents.manufacturing_agent import ManufacturingAgent
from app.agents.sales_agent import SalesAgent
from app.agents.supply_chain_agent import SupplyChainAgent
from app.services.integrations.jde_prompt_executor import JDEPromptExecutionError, JDEPromptExecutor
from app.services.orchestration.autoerp_agents import AutoERPAgentSuite
from app.services.orchestration.state import AutoERPGeneratorState
from app.services.realtime import websocket_hub

GENERATION_JOBS: dict[str, dict[str, Any]] = {}


class AutoERPRuntime:
    def __init__(self) -> None:
        self.suite = AutoERPAgentSuite()

    async def run_generation(self, generation_id: str) -> None:
        job = GENERATION_JOBS[generation_id]
        state: AutoERPGeneratorState = job["state"]
        steps = [
            ("Parsing requirements", self.suite.requirement_parser.run),
            ("Designing schema", self.suite.schema_designer.run),
            ("Generating code", self.suite.code_generator.run),
            ("Generating config", self.suite.config_generator.run),
            ("Initializing master data", self.suite.master_data_initializer.run),
        ]
        try:
            total_steps = len(steps)
            for index, (label, runner) in enumerate(steps, start=1):
                await websocket_hub.broadcast(
                    f"generate:{generation_id}",
                    {
                        "type": "progress",
                        "content": f"{label}...",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "metadata": {"step": index, "progress": int((index - 1) / total_steps * 100)},
                    },
                )
                result = runner(state)
                state = result.state
                job["state"] = state
                await websocket_hub.broadcast(
                    f"generate:{generation_id}",
                    {
                        "type": "progress",
                        "content": f"{label} completed",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "metadata": {"step": index, "progress": int(index / total_steps * 100)},
                    },
                )
            job["status"] = "completed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            await websocket_hub.broadcast(
                f"generate:{generation_id}",
                {
                    "type": "message",
                    "content": "ERP generation completed successfully.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "metadata": {"progress": 100},
                },
            )
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            await websocket_hub.broadcast(
                f"generate:{generation_id}",
                {
                    "type": "error",
                    "content": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "metadata": {},
                },
            )

    @staticmethod
    def package_generation(generation_id: str) -> bytes:
        job = GENERATION_JOBS[generation_id]
        state: AutoERPGeneratorState = job["state"]
        files = {}
        files.update(state.generated_code)
        files.update(state.generated_configs)
        files["schema.json"] = json.dumps(state.schema_design, indent=2)
        files["master_data.json"] = json.dumps(state.master_data, indent=2)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, content in files.items():
                archive.writestr(filename, content if isinstance(content, str) else json.dumps(content, indent=2))
        buffer.seek(0)
        return buffer.read()


class CopilotRuntime:
    AGENTS = {
        "finance": FinanceAgent,
        "supply_chain": SupplyChainAgent,
        "manufacturing": ManufacturingAgent,
        "sales": SalesAgent,
        "hr": HRAgent,
    }

    def route_module(self, query: str, requested_module: str | None = None) -> str:
        if requested_module in self.AGENTS:
            return requested_module
        lowered = query.lower()
        if any(keyword in lowered for keyword in ("invoice", "gl", "ap", "ar", "budget", "trial balance")):
            return "finance"
        if any(keyword in lowered for keyword in ("inventory", "vendor", "po", "purchase order")):
            return "supply_chain"
        if any(keyword in lowered for keyword in ("work order", "production", "bom", "capacity")):
            return "manufacturing"
        if any(keyword in lowered for keyword in ("sales", "quote", "forecast", "customer order")):
            return "sales"
        if any(keyword in lowered for keyword in ("employee", "payroll", "benefits", "attendance")):
            return "hr"
        return "finance"

    async def respond(self, session_id: str, query: str, context: dict[str, Any] | None = None, requested_module: str | None = None) -> dict[str, Any]:
        module = self.route_module(query, requested_module)
        agent = self.AGENTS[module]()
        response = agent.handle(query, context or {})
        chunks = response.summary.split(". ")
        assembled = ""
        for chunk in chunks:
            assembled = f"{assembled}{chunk}. ".strip()
            await websocket_hub.broadcast(
                f"chat:{session_id}",
                {
                    "type": "message",
                    "content": assembled,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "metadata": {"module": module},
                },
            )
        return {
            "module": module,
            "answer": response.summary,
            "data": response.data,
            "recommended_actions": response.recommended_actions,
        }

    async def execute(
        self,
        session_id: str,
        query: str,
        *,
        context: dict[str, Any] | None = None,
        requested_module: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        module = self.route_module(query, requested_module)
        executor = JDEPromptExecutor()
        try:
            plan = executor.plan(query, requested_module=module)
        except JDEPromptExecutionError as exc:
            return {
                "status": "error",
                "module": module,
                "action_type": None,
                "answer": str(exc),
                "execution_plan": None,
                "result": None,
            }

        await websocket_hub.broadcast(
            f"chat:{session_id}",
            {
                "type": "message",
                "content": plan.summary,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"module": module, "action_type": plan.action_type, "mode": "plan"},
            },
        )

        if not confirm:
            return {
                "status": "planned",
                "module": module,
                "action_type": plan.action_type,
                "answer": "Execution plan created. Re-submit with confirm=true to execute in JD Edwards.",
                "execution_plan": {
                    "action_type": plan.action_type,
                    "module": plan.module,
                    "target_system": "jd_edwards",
                    "requires_confirmation": True,
                    "parsed_payload": plan.parsed_payload,
                    "summary": plan.summary,
                },
                "result": None,
            }

        try:
            result = executor.execute(plan)
        except JDEPromptExecutionError as exc:
            return {
                "status": "error",
                "module": module,
                "action_type": plan.action_type,
                "answer": str(exc),
                "execution_plan": {
                    "action_type": plan.action_type,
                    "module": plan.module,
                    "target_system": "jd_edwards",
                    "requires_confirmation": True,
                    "parsed_payload": plan.parsed_payload,
                    "summary": plan.summary,
                },
                "result": None,
            }

        await websocket_hub.broadcast(
            f"chat:{session_id}",
            {
                "type": "message",
                "content": f"Executed {plan.action_type} in JD Edwards.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"module": module, "action_type": plan.action_type, "mode": "execute"},
            },
        )
        return {
            "status": "executed",
            "module": module,
            "action_type": plan.action_type,
            "answer": f"Executed action in JD Edwards: {plan.summary}",
            "execution_plan": {
                "action_type": plan.action_type,
                "module": plan.module,
                "target_system": "jd_edwards",
                "requires_confirmation": True,
                "parsed_payload": plan.parsed_payload,
                "summary": plan.summary,
            },
            "result": result,
        }


autoerp_runtime = AutoERPRuntime()
copilot_runtime = CopilotRuntime()
