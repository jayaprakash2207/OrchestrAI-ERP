from app.agents.base_copilot import BaseCopilotAgent


class HRAgent(BaseCopilotAgent):
    module_name = "hr"

    def fetch_data(self, query: str, context: dict) -> dict:
        return {
            "employees": [
                {"employee_id": "EMP001", "name": "Alex Carter", "department": "Finance", "status": "ACTIVE"},
                {"employee_id": "EMP002", "name": "Priya Raman", "department": "HR", "status": "ACTIVE"},
            ],
            "context": context,
        }

    def recommend_actions(self, query: str, data: dict) -> list[str]:
        return ["Review payroll summary", "Check HR approvals"]
