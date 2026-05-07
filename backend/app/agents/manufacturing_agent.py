from app.agents.base_copilot import BaseCopilotAgent


class ManufacturingAgent(BaseCopilotAgent):
    module_name = "manufacturing"

    def fetch_data(self, query: str, context: dict) -> dict:
        return {
            "work_orders": [
                {"work_order": "WO-001", "status": "OPEN", "priority": "HIGH", "due_date": "2026-04-08"},
                {"work_order": "WO-002", "status": "IN_PROGRESS", "priority": "MEDIUM", "due_date": "2026-04-10"},
            ],
            "context": context,
        }

    def recommend_actions(self, query: str, data: dict) -> list[str]:
        return ["Review capacity bottlenecks", "Release urgent work orders"]
