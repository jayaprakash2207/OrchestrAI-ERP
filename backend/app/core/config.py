import json
import logging
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def configure_logging(log_level: str, log_format: str = "text") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    class RedactSecretsFilter(logging.Filter):
        REDACTION_MARKERS = ("password", "secret", "token", "api_key", "authorization", "cookie")

        def filter(self, record: logging.LogRecord) -> bool:
            if isinstance(record.args, dict):
                redacted: dict[str, Any] = {}
                for key, value in record.args.items():
                    redacted[key] = "***REDACTED***" if any(marker in key.lower() for marker in self.REDACTION_MARKERS) else value
                record.args = redacted
            return True

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    if log_format == "json":
        formatter = logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
        )
    else:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    handler.addFilter(RedactSecretsFilter())

    root_logger.setLevel(level)
    root_logger.addHandler(handler)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    project_name: str = Field(default="AI ERP Platform")
    environment: Literal["development", "staging", "production", "test"] = Field(default="development")
    api_v1_prefix: str = Field(default="/api/v1")

    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    backend_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    log_format: Literal["text", "json"] = Field(default="text")
    log_sql_queries: bool = Field(default=False)

    jwt_secret_key: SecretStr = Field(default=SecretStr("change-me"))
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=60)

    postgres_db: str = Field(default="ai_erp")
    postgres_user: str = Field(default="postgres")
    postgres_password: SecretStr = Field(default=SecretStr("postgres"))
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    database_url: str | None = Field(default=None)
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=20)
    db_pool_timeout: int = Field(default=30)
    db_pool_recycle: int = Field(default=1800)
    db_connect_timeout: int = Field(default=10)
    db_retry_attempts: int = Field(default=5)
    db_retry_min_wait_seconds: int = Field(default=1)
    db_retry_max_wait_seconds: int = Field(default=10)
    db_startup_check_enabled: bool = Field(default=True)
    db_statement_timeout_ms: int = Field(default=30000)

    chroma_host: str = Field(default="chromadb")
    chroma_port: int = Field(default=8001)
    chroma_collection_prefix: str = Field(default="ai_erp")
    chroma_jde_collection_name: str = Field(default="jde_knowledge")
    chroma_healthcheck_timeout_seconds: int = Field(default=5)
    chroma_retrieval_limit: int = Field(default=5)
    chroma_similarity_threshold: float = Field(default=0.2)

    gemini_api_key: SecretStr = Field(default=SecretStr(""))
    gemini_model: str = Field(default="gemini-2.0-flash")
    gemini_temperature: float = Field(default=0.2)
    gemini_max_output_tokens: int = Field(default=4096)
    gemini_healthcheck_timeout_seconds: int = Field(default=5)
    gemini_reasoning_max_tokens: int = Field(default=2000)
    gemini_code_max_tokens: int = Field(default=8000)
    gemini_retry_attempts: int = Field(default=3)
    gemini_daily_token_budget: int = Field(default=500000)
    gemini_monthly_token_budget: int = Field(default=10000000)
    gemini_cost_per_1k_input_tokens: float = Field(default=0.00015)
    gemini_cost_per_1k_output_tokens: float = Field(default=0.0006)
    llm_cache_ttl_seconds: int = Field(default=86400)
    retrieval_cache_ttl_seconds: int = Field(default=86400)

    jde_connection_mode: Literal["api", "database", "hybrid"] = Field(default="api")
    jde_api_base_url: str | None = Field(default=None)
    jde_api_username: str | None = Field(default=None)
    jde_api_password: SecretStr | None = Field(default=None)
    jde_api_token: SecretStr | None = Field(default=None)
    jde_oauth_client_id: str | None = Field(default=None)
    jde_oauth_client_secret: SecretStr | None = Field(default=None)
    jde_oauth_token_url: str | None = Field(default=None)
    jde_api_timeout_seconds: int = Field(default=30)
    jde_database_url: str | None = Field(default=None)
    jde_database_user: str | None = Field(default=None)
    jde_database_password: SecretStr | None = Field(default=None)
    jde_environment: str | None = Field(default=None)
    jde_role: str | None = Field(default=None)
    jde_db_query_timeout_seconds: int = Field(default=30)
    jde_cache_vendor_ttl_seconds: int = Field(default=3600)
    jde_cache_customer_ttl_seconds: int = Field(default=3600)
    jde_cache_gl_ttl_seconds: int = Field(default=86400)
    jde_cache_volatile_ttl_seconds: int = Field(default=300)

    feature_autoerp_enabled: bool = Field(default=True)
    feature_jde_copilot_enabled: bool = Field(default=True)
    feature_jde_api_ingestion_enabled: bool = Field(default=True)
    feature_jde_database_ingestion_enabled: bool = Field(default=False)
    feature_langgraph_tracing_enabled: bool = Field(default=False)
    mock_llm_mode: bool = Field(default=False)
    gemini_fallback_to_mock: bool = Field(default=True)

    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests_per_minute: int = Field(default=100)
    rate_limit_burst: int = Field(default=30)

    finance_ap_approval_threshold: int = Field(default=10000)
    finance_ap_payable_account_number: str = Field(default="2000")
    finance_cash_account_number: str = Field(default="1000")

    redis_enabled: bool = Field(default=True)
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_password: SecretStr | None = Field(default=None)
    redis_url: str | None = Field(default=None)

    langchain_tracing_v2: bool = Field(default=False)
    langchain_api_key: SecretStr | None = Field(default=None)
    langchain_project: str = Field(default="ai-erp-platform")
    state_storage_path: str = Field(default="data/state")

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def model_post_init(self, __context: Any) -> None:
        if not self.database_url:
            self.database_url = (
                "postgresql+psycopg://"
                f"{self.postgres_user}:{self.postgres_password.get_secret_value()}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if not self.redis_url:
            auth_segment = ""
            if self.redis_password and self.redis_password.get_secret_value():
                auth_segment = f":{self.redis_password.get_secret_value()}@"
            self.redis_url = f"redis://{auth_segment}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def validate_runtime_requirements(self) -> None:
        missing: list[str] = []

        if self.environment != "test" and not self.gemini_api_key.get_secret_value().strip():
            missing.append("GEMINI_API_KEY")

        if self.environment == "production" and self.jwt_secret_key.get_secret_value() == "change-me":
            missing.append("JWT_SECRET_KEY must not use the default value in production")

        if self.jde_connection_mode in {"api", "hybrid"} and not self.jde_api_base_url:
            missing.append("JDE_API_BASE_URL")

        if self.jde_connection_mode in {"database", "hybrid"} and not self.jde_database_url:
            missing.append("JDE_DATABASE_URL")

        if missing:
            raise ValueError(f"Missing or invalid required settings: {', '.join(missing)}")

    def sanitized_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        sensitive_keys = {
            "jwt_secret_key",
            "postgres_password",
            "database_url",
            "gemini_api_key",
            "jde_api_password",
            "jde_api_token",
            "jde_oauth_client_secret",
            "jde_database_url",
            "jde_database_password",
            "redis_password",
            "redis_url",
            "langchain_api_key",
        }
        for key in sensitive_keys:
            if key in data and data[key] is not None:
                data[key] = "***REDACTED***"
        return data

    def log_startup_config(self) -> None:
        logger = logging.getLogger("app.config")
        logger.info("Application configuration loaded: %s", json.dumps(self.sanitized_dict(), sort_keys=True))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format)
    return settings


settings = get_settings()
