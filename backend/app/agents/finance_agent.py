from app.agents.base_copilot import BaseCopilotAgent


class FinanceAgent(BaseCopilotAgent):
    module_name = "finance"

    def fetch_data(self, query: str, context: dict) -> dict:
        lowered = query.lower()
        if "vendor" in lowered or "invoice" in lowered or "ap" in lowered:
            return {"invoices": self.connector.get_ap_invoices()}
        if "account" in lowered or "gl" in lowered or "trial balance" in lowered:
            return {"gl_accounts": self.connector.get_gl_accounts(context.get("company_id"))}
        return super().fetch_data(query, context)

    def recommend_actions(self, query: str, data: dict) -> list[str]:
        if "invoices" in data:
            return ["Review overdue invoices", "Open AP aging report"]
        if "gl_accounts" in data:
            return ["Run trial balance", "Review journal entries"]
        return ["Ask a finance-specific question"]
