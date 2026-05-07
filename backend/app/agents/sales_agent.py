from app.agents.base_copilot import BaseCopilotAgent


class SalesAgent(BaseCopilotAgent):
    module_name = "sales"

    def fetch_data(self, query: str, context: dict) -> dict:
        if "customer" in query.lower():
            return {"customers": self.connector.get_customers()}
        return {
            "sales_orders": [
                {"order_number": "SO-001", "customer": "ABC Corporation", "status": "OPEN", "amount": 15000},
                {"order_number": "SO-002", "customer": "XYZ Industries", "status": "SHIPPED", "amount": 42000},
            ],
            "context": context,
        }

    def recommend_actions(self, query: str, data: dict) -> list[str]:
        return ["Review customer credit status", "Create follow-up quote"]
