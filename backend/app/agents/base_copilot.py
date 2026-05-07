from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.chromadb_rag import ChromaKnowledgeService
from app.integrations.gemini_llm import GeminiClient
from app.integrations.jde_connector import JDEConnectorFactory


@dataclass
class CopilotResponse:
    summary: str
    data: Any
    recommended_actions: list[str]


class BaseCopilotAgent:
    module_name = "general"

    def __init__(self) -> None:
        self.llm = GeminiClient()
        self.rag = ChromaKnowledgeService()
        self.connector = JDEConnectorFactory.create()

    def handle(self, query: str, context: dict | None = None) -> CopilotResponse:
        knowledge = self.rag.retrieve(query, module=self.module_name)
        data = self.fetch_data(query, context or {})
        summary = self.summarize(query, data, knowledge)
        return CopilotResponse(summary=summary, data=data, recommended_actions=self.recommend_actions(query, data))

    def fetch_data(self, query: str, context: dict) -> Any:
        return {"query": query, "context": context}

    def summarize(self, query: str, data: Any, knowledge: list) -> str:
        prompt = f"Module: {self.module_name}\nQuery: {query}\nData: {data}\nKnowledge: {[doc.content for doc in knowledge[:3]]}"
        result = self.llm.generate(system_prompt="You are a business ERP copilot.", user_prompt=prompt, task_type="reasoning")
        return result.text or f"{self.module_name.title()} response generated."

    def recommend_actions(self, query: str, data: Any) -> list[str]:
        return []
