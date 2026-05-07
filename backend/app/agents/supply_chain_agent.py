from app.agents.base_copilot import BaseCopilotAgent


class SupplyChainAgent(BaseCopilotAgent):
    module_name = "supply_chain"

    def fetch_data(self, query: str, context: dict) -> dict:
        lowered = query.lower()
        if "po" in lowered or "purchase order" in lowered:
            return {"purchase_orders": self.connector.get_purchase_orders()}
        if "vendor" in lowered:
            return {"vendors": self.connector.get_vendors()}
        return super().fetch_data(query, context)
