from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

import google.generativeai as genai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger("app.ai.gemini")


@dataclass
class GeminiUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    latency_ms: float


@dataclass
class GeminiResult:
    text: str
    usage: GeminiUsage
    parsed_json: dict[str, Any] | list[Any] | None = None


class InMemoryTTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[datetime, Any]] = {}

    def get(self, key: str) -> Any | None:
        cached = self._store.get(key)
        if not cached:
            return None
        created_at, value = cached
        if datetime.utcnow() - created_at > timedelta(seconds=self.ttl_seconds):
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (datetime.utcnow(), value)


class CostTracker:
    def __init__(self) -> None:
        self.daily_usage: dict[str, int] = {}
        self.monthly_usage: dict[str, int] = {}

    def record(self, tokens: int) -> None:
        today_key = date.today().isoformat()
        month_key = date.today().strftime("%Y-%m")
        self.daily_usage[today_key] = self.daily_usage.get(today_key, 0) + tokens
        self.monthly_usage[month_key] = self.monthly_usage.get(month_key, 0) + tokens
        if self.daily_usage[today_key] > settings.gemini_daily_token_budget:
            logger.warning("Daily Gemini token budget exceeded: %s", self.daily_usage[today_key])
        if self.monthly_usage[month_key] > settings.gemini_monthly_token_budget:
            logger.warning("Monthly Gemini token budget exceeded: %s", self.monthly_usage[month_key])


class GeminiClient:
    def __init__(self) -> None:
        genai.configure(api_key=settings.gemini_api_key.get_secret_value())
        self.cache = InMemoryTTLCache(settings.llm_cache_ttl_seconds)
        self.cost_tracker = CostTracker()

    def _model(self, temperature: float, max_output_tokens: int):
        return genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def extract_json(text: str) -> dict[str, Any] | list[Any] | None:
        fenced = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
        candidate = fenced.group(1) if fenced else text.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None

    @retry(
        stop=stop_after_attempt(settings.gemini_retry_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _invoke(self, system_prompt: str, user_prompt: str, temperature: float, max_output_tokens: int):
        model = self._model(temperature, max_output_tokens)
        return model.generate_content([system_prompt, user_prompt])

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        task_type: Literal["reasoning", "code", "creative"] = "reasoning",
        cache_key: str | None = None,
    ) -> GeminiResult:
        temperature = 0.7 if task_type == "creative" else 0.3
        max_tokens = settings.gemini_code_max_tokens if task_type == "code" else settings.gemini_reasoning_max_tokens
        cache_key = cache_key or f"{task_type}:{hash((system_prompt, user_prompt, temperature, max_tokens))}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        started_at = datetime.utcnow()
        logger.info("Gemini request started task_type=%s prompt_preview=%s", task_type, user_prompt[:500])
        response = self._invoke(system_prompt, user_prompt, temperature, max_tokens)
        latency_ms = (datetime.utcnow() - started_at).total_seconds() * 1000
        text = getattr(response, "text", "") or ""
        input_tokens = self._estimate_tokens(system_prompt + user_prompt)
        output_tokens = self._estimate_tokens(text)
        total_tokens = input_tokens + output_tokens
        estimated_cost = (input_tokens / 1000 * settings.gemini_cost_per_1k_input_tokens) + (
            output_tokens / 1000 * settings.gemini_cost_per_1k_output_tokens
        )
        usage = GeminiUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
            latency_ms=latency_ms,
        )
        result = GeminiResult(text=text, usage=usage, parsed_json=self.extract_json(text))
        self.cost_tracker.record(total_tokens)
        logger.info(
            "Gemini request completed input_tokens=%s output_tokens=%s total_tokens=%s latency_ms=%.2f estimated_cost=%.6f",
            input_tokens,
            output_tokens,
            total_tokens,
            latency_ms,
            estimated_cost,
        )
        self.cache.set(cache_key, result)
        return result
