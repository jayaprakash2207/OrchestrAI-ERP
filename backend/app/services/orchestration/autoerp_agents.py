from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import settings
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.prompt_templates import CODE_GENERATION_PROMPT, REQUIREMENT_PARSING_PROMPT, SCHEMA_DESIGN_PROMPT
from app.services.orchestration.persistence import StatePersistence
from app.services.orchestration.state import AutoERPGeneratorState, Message, Requirement

logger = logging.getLogger("app.orchestration.autoerp_agents")

VALID_REQUIREMENT_TYPES = {
    "ACCOUNTING_STRUCTURE",
    "APPROVAL_WORKFLOW",
    "CURRENCY",
    "DIMENSION",
    "REPORT",
    "INTEGRATION",
    "COMPLIANCE",
}

VALID_CURRENCY_CODES = {
    "USD",
    "EUR",
    "GBP",
    "INR",
    "JPY",
    "AUD",
    "CAD",
    "SGD",
    "AED",
}

DEFAULT_COST_CENTERS = ["Sales", "Operations", "Finance", "HR", "IT"]
DEFAULT_CURRENCIES = ["USD", "EUR", "GBP"]
DEFAULT_APPROVAL_RULES = [
    {"document_type": "ap_invoice", "amount_threshold": 1000, "approval_levels_required": 0},
    {"document_type": "ap_invoice", "amount_threshold": 10000, "approval_levels_required": 1},
    {"document_type": "ap_invoice", "amount_threshold": 10001, "approval_levels_required": 2},
    {"document_type": "purchase_order", "amount_threshold": 50000, "approval_levels_required": 1},
]
STANDARD_GL_ACCOUNTS = [
    ("1000", "Assets", "ASSET", None),
    ("1100", "Cash and Cash Equivalents", "ASSET", "1000"),
    ("1110", "Operating Cash Account", "ASSET", "1100"),
    ("1120", "Savings Account", "ASSET", "1100"),
    ("1200", "Accounts Receivable", "ASSET", "1000"),
    ("1210", "Trade Receivables", "ASSET", "1200"),
    ("1220", "Allowance for Doubtful Accounts", "ASSET", "1200"),
    ("1300", "Inventory", "ASSET", "1000"),
    ("1310", "Raw Materials", "ASSET", "1300"),
    ("1320", "Work in Process", "ASSET", "1300"),
    ("1330", "Finished Goods", "ASSET", "1300"),
    ("1400", "Other Current Assets", "ASSET", "1000"),
    ("1500", "Fixed Assets", "ASSET", "1000"),
    ("1510", "Property and Equipment", "ASSET", "1500"),
    ("1520", "Accumulated Depreciation", "ASSET", "1500"),
    ("1600", "Other Long-Term Assets", "ASSET", "1000"),
    ("2000", "Liabilities", "LIABILITY", None),
    ("2100", "Accounts Payable", "LIABILITY", "2000"),
    ("2110", "Trade Payables", "LIABILITY", "2100"),
    ("2120", "Accrued Expenses", "LIABILITY", "2100"),
    ("2200", "Short-Term Debt", "LIABILITY", "2000"),
    ("2300", "Other Current Liabilities", "LIABILITY", "2000"),
    ("2400", "Long-Term Liabilities", "LIABILITY", "2000"),
    ("2410", "Long-Term Debt", "LIABILITY", "2400"),
    ("2420", "Deferred Tax Liability", "LIABILITY", "2400"),
    ("3000", "Equity", "EQUITY", None),
    ("3100", "Common Stock", "EQUITY", "3000"),
    ("3200", "Retained Earnings", "EQUITY", "3000"),
    ("3300", "Current Period Income", "EQUITY", "3000"),
    ("4000", "Revenue", "REVENUE", None),
    ("4100", "Product Revenue", "REVENUE", "4000"),
    ("4200", "Service Revenue", "REVENUE", "4000"),
    ("4300", "Other Income", "REVENUE", "4000"),
    ("4400", "Sales Returns and Allowances", "REVENUE", "4000"),
    ("5000", "Expenses", "EXPENSE", None),
    ("5100", "Cost of Goods Sold", "EXPENSE", "5000"),
    ("5110", "Materials", "EXPENSE", "5100"),
    ("5120", "Labor", "EXPENSE", "5100"),
    ("5130", "Manufacturing Overhead", "EXPENSE", "5100"),
    ("5200", "Operating Expenses", "EXPENSE", "5000"),
    ("5210", "Salaries and Wages", "EXPENSE", "5200"),
    ("5220", "Office Rent", "EXPENSE", "5200"),
    ("5230", "Utilities", "EXPENSE", "5200"),
    ("5240", "Office Supplies", "EXPENSE", "5200"),
    ("5250", "Professional Fees", "EXPENSE", "5200"),
    ("5300", "Depreciation and Amortization", "EXPENSE", "5000"),
    ("5400", "Interest Expense", "EXPENSE", "5000"),
    ("5500", "Other Expenses", "EXPENSE", "5000"),
]


@dataclass
class AgentRunResult:
    state: AutoERPGeneratorState
    output: Any


class RequirementParserAgent:
    def __init__(self, llm_client: GeminiClient | None = None, persistence: StatePersistence | None = None) -> None:
        self.llm = llm_client or GeminiClient()
        self.persistence = persistence or StatePersistence()

    def run(self, state: AutoERPGeneratorState) -> AgentRunResult:
        logger.info("Requirement parser started generation_id=%s", state.generation_id)
        raw_requirements: list[dict[str, Any]] = []
        token_count = 0
        try:
            if settings.mock_llm_mode:
                raise RuntimeError("Mock LLM mode enabled")
            user_prompt = self._build_prompt(state.requirements_input, state.company_name)
            result = self.llm.generate(
                system_prompt=REQUIREMENT_PARSING_PROMPT,
                user_prompt=user_prompt,
                task_type="reasoning",
                cache_key=f"requirement_parser:{state.generation_id}:{hash(state.requirements_input)}",
            )
            token_count = result.usage.total_tokens
            requirements_payload = result.parsed_json
            if requirements_payload is None:
                logger.warning("Requirement parser JSON extraction failed, retrying with stricter prompt.")
                retry_prompt = f"{user_prompt}\n\nReturn only strict JSON with a top-level 'requirements' array."
                result = self.llm.generate(
                    system_prompt=REQUIREMENT_PARSING_PROMPT,
                    user_prompt=retry_prompt,
                    task_type="reasoning",
                    cache_key=f"requirement_parser_retry:{state.generation_id}:{hash(state.requirements_input)}",
                )
                token_count = result.usage.total_tokens
                requirements_payload = result.parsed_json

            if isinstance(requirements_payload, dict):
                raw_requirements = requirements_payload.get("requirements", [])
            elif isinstance(requirements_payload, list):
                raw_requirements = requirements_payload
        except Exception as exc:
            if not settings.gemini_fallback_to_mock:
                raise
            logger.warning("Requirement parser falling back to mock mode: %s", exc)
            raw_requirements = _fallback_requirements(state.requirements_input)

        validated = self._validate_requirements(raw_requirements)
        state.parsed_requirements = validated
        state.current_step = 2
        state.error = None
        state.messages.append(
            Message(
                role="assistant",
                content=f"Parsed {len(validated)} requirements.",
                metadata={"agent": "RequirementParserAgent", "tokens": token_count, "mode": "mock" if token_count == 0 else "gemini"},
            )
        )
        self.persistence.save("autoerp_generator", state.generation_id, state)
        return AgentRunResult(state=state, output=validated)

    @staticmethod
    def _build_prompt(requirements_input: str, company_name: str) -> str:
        return (
            f"Company name: {company_name or 'Unknown'}\n"
            f"Requirement text:\n{requirements_input}\n\n"
            "Extract requirement objects with fields: type, description, priority, parameters, confidence_score."
        )

    def _validate_requirements(self, raw_requirements: list[dict[str, Any]]) -> list[Requirement]:
        validated: list[Requirement] = []
        seen_keys: set[str] = set()
        for raw in raw_requirements:
            requirement = Requirement.model_validate(raw)
            self._validate_requirement_parameters(requirement)
            dedupe_key = json.dumps({"type": requirement.type, "description": requirement.description, "parameters": requirement.parameters}, sort_keys=True, default=str)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            validated.append(requirement)
        return validated

    @staticmethod
    def _validate_requirement_parameters(requirement: Requirement) -> None:
        parameters = requirement.parameters
        if requirement.type == "ACCOUNTING_STRUCTURE":
            cost_centers = parameters.get("cost_centers")
            if cost_centers is not None and not cost_centers:
                raise ValueError("Cost centers cannot be empty when specified.")
        elif requirement.type == "CURRENCY":
            currencies = parameters.get("currencies", [])
            invalid = [currency for currency in currencies if currency.upper() not in VALID_CURRENCY_CODES]
            if invalid:
                raise ValueError(f"Invalid currency codes: {', '.join(invalid)}")
        elif requirement.type == "APPROVAL_WORKFLOW":
            threshold = parameters.get("threshold")
            if threshold is not None:
                try:
                    if Decimal(str(threshold)) <= 0:
                        raise ValueError("Threshold must be positive.")
                except (InvalidOperation, TypeError) as exc:
                    raise ValueError("Threshold must be a valid positive number.") from exc


class SchemaDesignerAgent:
    ALWAYS_INCLUDE_TABLES = {
        "gl_accounts",
        "cost_centers",
        "currencies",
        "ap_invoices",
        "journal_entries",
        "vendors",
        "customers",
        "audit_log",
        "approval_workflows",
    }

    def __init__(self, llm_client: GeminiClient | None = None, persistence: StatePersistence | None = None) -> None:
        self.llm = llm_client or GeminiClient()
        self.persistence = persistence or StatePersistence()

    def run(self, state: AutoERPGeneratorState) -> AgentRunResult:
        logger.info("Schema designer started generation_id=%s", state.generation_id)
        requirements_payload = [requirement.model_dump() for requirement in state.parsed_requirements]
        token_count = 0
        try:
            if settings.mock_llm_mode:
                raise RuntimeError("Mock LLM mode enabled")
            user_prompt = (
                f"Company name: {state.company_name or 'Unknown'}\n"
                f"Requirements:\n{json.dumps(requirements_payload, indent=2)}\n\n"
                "Return JSON with tables, enums, constraints, and notes."
            )
            result = self.llm.generate(
                system_prompt=SCHEMA_DESIGN_PROMPT,
                user_prompt=user_prompt,
                task_type="reasoning",
                cache_key=f"schema_designer:{state.generation_id}:{hash(json.dumps(requirements_payload, sort_keys=True))}",
            )
            token_count = result.usage.total_tokens
            schema = result.parsed_json if isinstance(result.parsed_json, dict) else {}
        except Exception as exc:
            if not settings.gemini_fallback_to_mock:
                raise
            logger.warning("Schema designer falling back to mock mode: %s", exc)
            schema = _fallback_schema(state.company_name, state.parsed_requirements)
        self._validate_schema(schema)
        state.schema_design = schema
        state.current_step = 3
        state.error = None
        state.messages.append(
            Message(
                role="assistant",
                content="Generated schema design.",
                metadata={"agent": "SchemaDesignerAgent", "tokens": token_count, "mode": "mock" if token_count == 0 else "gemini"},
            )
        )
        self.persistence.save("autoerp_generator", state.generation_id, state)
        return AgentRunResult(state=state, output=schema)

    def _validate_schema(self, schema: dict[str, Any]) -> None:
        tables = schema.get("tables", [])
        if not tables:
            raise ValueError("Schema must contain tables.")
        table_names = {table.get("name") for table in tables}
        missing = self.ALWAYS_INCLUDE_TABLES - table_names
        if missing:
            raise ValueError(f"Missing required tables: {', '.join(sorted(missing))}")
        for table in tables:
            columns = table.get("columns", [])
            if not any(column.get("primary_key") for column in columns):
                raise ValueError(f"Table {table.get('name')} must define a primary key.")
        relationships = schema.get("relationships", [])
        for relationship in relationships:
            if relationship.get("from_table") not in table_names or relationship.get("to_table") not in table_names:
                raise ValueError("Schema contains orphaned foreign key relationships.")


class CodeGeneratorAgent:
    REQUIRED_FILES = {"models.py", "schemas.py", "routes.py", "database.py", "main.py"}

    def __init__(self, llm_client: GeminiClient | None = None, persistence: StatePersistence | None = None) -> None:
        self.llm = llm_client or GeminiClient()
        self.persistence = persistence or StatePersistence()

    def run(self, state: AutoERPGeneratorState) -> AgentRunResult:
        logger.info("Code generator started generation_id=%s", state.generation_id)
        token_count = 0
        try:
            if settings.mock_llm_mode:
                raise RuntimeError("Mock LLM mode enabled")
            user_prompt = (
                f"Company name: {state.company_name or 'Unknown'}\n"
                f"Schema definition:\n{json.dumps(state.schema_design, indent=2)}\n"
                f"Requirements:\n{json.dumps([requirement.model_dump() for requirement in state.parsed_requirements], indent=2)}\n\n"
                "Return JSON with keys models.py, schemas.py, routes.py, database.py, main.py. "
                "Each value must be a complete Python source string."
            )
            result = self.llm.generate(
                system_prompt=CODE_GENERATION_PROMPT,
                user_prompt=user_prompt,
                task_type="code",
                cache_key=f"code_generator:{state.generation_id}:{hash(json.dumps(state.schema_design, sort_keys=True))}",
            )
            token_count = result.usage.total_tokens
            files = self._extract_code_files(result)
        except Exception as exc:
            if not settings.gemini_fallback_to_mock:
                raise
            logger.warning("Code generator falling back to mock mode: %s", exc)
            files = _fallback_code_files(state.company_name, state.parsed_requirements)
        self._validate_generated_files(files)
        state.generated_code = files
        state.current_step = 4
        state.error = None
        state.messages.append(
            Message(
                role="assistant",
                content="Generated code artifacts.",
                metadata={"agent": "CodeGeneratorAgent", "tokens": token_count, "mode": "mock" if token_count == 0 else "gemini"},
            )
        )
        self.persistence.save("autoerp_generator", state.generation_id, state)
        return AgentRunResult(state=state, output=files)

    def _extract_code_files(self, result) -> dict[str, str]:
        if isinstance(result.parsed_json, dict):
            files = {filename: str(content) for filename, content in result.parsed_json.items()}
            if files:
                return files
        text = result.text.strip()
        code_blocks = re.findall(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
        if code_blocks:
            fallback_names = ["models.py", "schemas.py", "routes.py", "database.py", "main.py"]
            return {fallback_names[index]: block.strip() for index, block in enumerate(code_blocks[: len(fallback_names)])}
        return {}

    def _validate_generated_files(self, files: dict[str, str]) -> None:
        missing = self.REQUIRED_FILES - set(files)
        if missing:
            raise ValueError(f"Generated code is missing files: {', '.join(sorted(missing))}")
        for filename, code in files.items():
            if not code.strip():
                raise ValueError(f"Generated file {filename} is empty.")
            if "import " not in code and "from " not in code:
                raise ValueError(f"Generated file {filename} does not appear to contain valid Python code.")


class ConfigGeneratorAgent:
    def __init__(self, persistence: StatePersistence | None = None) -> None:
        self.persistence = persistence or StatePersistence()

    def run(self, state: AutoERPGeneratorState) -> AgentRunResult:
        logger.info("Config generator started generation_id=%s", state.generation_id)
        currencies = _extract_currencies(state.parsed_requirements)
        approval = _extract_approval_requirements(state.parsed_requirements)
        files = {
            "docker-compose.yml": self._docker_compose(),
            "Dockerfile": self._dockerfile(),
            ".env.example": self._env_example(state.company_name, currencies, approval),
            "setup.sh": self._setup_script(),
            "alembic.ini": self._alembic_ini(),
        }
        state.generated_configs = files
        state.current_step = 5
        state.error = None
        state.messages.append(
            Message(
                role="assistant",
                content="Generated deployment and configuration files.",
                metadata={"agent": "ConfigGeneratorAgent", "files": list(files)},
            )
        )
        self.persistence.save("autoerp_generator", state.generation_id, state)
        return AgentRunResult(state=state, output=files)

    @staticmethod
    def _docker_compose() -> str:
        return """version: "3.9"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${DB_USER:-erp_user}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-change_me}
      POSTGRES_DB: ${DB_NAME:-erp_db}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-erp_user} -d ${DB_NAME:-erp_db}"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: ${DATABASE_URL}
      API_PORT: ${API_PORT:-8000}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY}
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/data

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    depends_on:
      - api
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    ports:
      - "3000:3000"

volumes:
  postgres_data:
  chroma_data:
"""

    @staticmethod
    def _dockerfile() -> str:
        return """FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    postgresql-client \\
    libpq-dev \\
    curl \\
    unixodbc \\
    unixodbc-dev \\
    freetds-dev \\
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN useradd --uid 1000 --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \\
  CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

    @staticmethod
    def _env_example(company_name: str, currencies: list[str], approval: dict[str, Any]) -> str:
        threshold = approval.get("threshold", 10000)
        levels = approval.get("approval_levels", 2)
        base_currency = currencies[0] if currencies else "USD"
        currency_csv = ",".join(currencies or DEFAULT_CURRENCIES)
        safe_company = company_name or "Your Company"
        return f"""# Company Configuration
COMPANY_NAME={safe_company}
COMPANY_ID=00001

# Database
DB_HOST=db
DB_PORT=5432
DB_USER=erp_user
DB_PASSWORD=change_me
DB_NAME=erp_db
DATABASE_URL=postgresql://erp_user:change_me@db:5432/erp_db

# API
API_PORT=8000
API_HOST=0.0.0.0
LOG_LEVEL=INFO

# Security
SECRET_KEY=your-secret-key-here-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Google Gemini
GOOGLE_API_KEY=your-api-key-here

# JD Edwards
JDE_API_URL=http://jde-server:8080/jderest/v3
JDE_API_USER=api_user
JDE_API_PASS=api_password
JDE_DB_CONNECTION=Driver=...;Server=...

# ChromaDB
CHROMADB_HOST=chroma
CHROMADB_PORT=8001

# Features
ENABLE_APPROVALS=true
APPROVAL_THRESHOLD={threshold}
APPROVAL_LEVELS={levels}

# Currencies
CURRENCIES={currency_csv}
BASE_CURRENCY={base_currency}
"""

    @staticmethod
    def _setup_script() -> str:
        return """#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install it from https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is not available. See https://docs.docker.com/compose/install/"
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "Python 3.11+ is required."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env created from .env.example. Please review and update values before production use."
fi

docker compose build
docker compose up -d db

until docker compose exec -T db pg_isready -U "${DB_USER:-erp_user}" -d "${DB_NAME:-erp_db}" >/dev/null 2>&1; do
  echo "Waiting for database to be healthy..."
  sleep 2
done

docker compose up -d api
docker compose exec api alembic upgrade head || {
  echo "Migration failed. Review alembic logs and consider rollback before retrying."
  exit 1
}

docker compose up -d chroma
docker compose up -d frontend

echo "Setup completed successfully."
echo "API: http://localhost:8000"
echo "Docs: http://localhost:8000/docs"
echo "Frontend: http://localhost:3000"
echo "DB: localhost:5432"
echo "Next steps:"
echo "  1. Edit .env if needed"
echo "  2. Access frontend at http://localhost:3000"
echo "  3. Use 'docker compose logs -f' to view logs"
echo "  4. Use 'docker compose down' to stop services"
"""

    @staticmethod
    def _alembic_ini() -> str:
        return """[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url = %(DATABASE_URL)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""


class MasterDataInitializerAgent:
    def __init__(self, persistence: StatePersistence | None = None) -> None:
        self.persistence = persistence or StatePersistence()

    def run(self, state: AutoERPGeneratorState) -> AgentRunResult:
        logger.info("Master data initializer started generation_id=%s", state.generation_id)
        cost_centers = _extract_cost_centers(state.parsed_requirements)
        currencies = _extract_currencies(state.parsed_requirements)
        approval_rules = _build_approval_rules(state.parsed_requirements)
        account_map: dict[str, dict[str, Any]] = {}
        gl_accounts = []
        for account_number, account_name, account_type, parent_account_number in STANDARD_GL_ACCOUNTS:
            account = {
                "account_number": account_number,
                "account_name": account_name,
                "account_type": account_type,
                "parent_account_id": parent_account_number,
                "is_active": True,
                "cost_center_code": None,
            }
            account_map[account_number] = account
            gl_accounts.append(account)

        data = {
            "gl_accounts": gl_accounts,
            "cost_centers": [
                {
                    "code": _cost_center_code(name),
                    "name": name,
                    "manager_id": None,
                    "budget": None,
                }
                for name in cost_centers
            ],
            "currencies": [
                {
                    "code": code,
                    "name": _currency_name(code),
                    "exchange_rate_to_base": 1.0 if index == 0 else round(1 + index * 0.05, 4),
                    "rate_date": date.today().isoformat(),
                }
                for index, code in enumerate(currencies)
            ],
            "vendors": _sample_vendors(),
            "customers": _sample_customers(),
            "approval_rules": approval_rules,
        }
        self._validate_master_data(data)
        state.master_data = data
        state.current_step = 6
        state.error = None
        state.messages.append(
            Message(
                role="assistant",
                content="Generated master_data.json content.",
                metadata={"agent": "MasterDataInitializerAgent", "sections": list(data)},
            )
        )
        self.persistence.save("autoerp_generator", state.generation_id, state)
        return AgentRunResult(state=state, output=data)

    @staticmethod
    def _validate_master_data(data: dict[str, Any]) -> None:
        account_numbers = [account["account_number"] for account in data["gl_accounts"]]
        if len(account_numbers) != len(set(account_numbers)):
            raise ValueError("GL accounts must have unique account numbers.")
        cost_center_codes = [center["code"] for center in data["cost_centers"]]
        if len(cost_center_codes) != len(set(cost_center_codes)):
            raise ValueError("Cost centers must have unique codes.")
        currencies = [currency["code"] for currency in data["currencies"]]
        if len(currencies) != len(set(currencies)):
            raise ValueError("Currencies must have unique codes.")
        account_lookup = {account["account_number"] for account in data["gl_accounts"]}
        for account in data["gl_accounts"]:
            parent = account["parent_account_id"]
            if parent and parent not in account_lookup:
                raise ValueError(f"GL hierarchy contains orphaned parent {parent}.")


def _extract_cost_centers(requirements: list[Requirement]) -> list[str]:
    for requirement in requirements:
        if requirement.type == "ACCOUNTING_STRUCTURE":
            cost_centers = requirement.parameters.get("cost_centers")
            if cost_centers:
                return [str(center).strip() for center in cost_centers if str(center).strip()]
    return DEFAULT_COST_CENTERS.copy()


def _extract_currencies(requirements: list[Requirement]) -> list[str]:
    for requirement in requirements:
        if requirement.type == "CURRENCY":
            currencies = requirement.parameters.get("currencies")
            if currencies:
                return [str(currency).upper() for currency in currencies if str(currency).upper() in VALID_CURRENCY_CODES]
    return DEFAULT_CURRENCIES.copy()


def _extract_approval_requirements(requirements: list[Requirement]) -> dict[str, Any]:
    for requirement in requirements:
        if requirement.type == "APPROVAL_WORKFLOW":
            return requirement.parameters
    return {"threshold": 10000, "approval_levels": 2}


def _build_approval_rules(requirements: list[Requirement]) -> list[dict[str, Any]]:
    parameters = _extract_approval_requirements(requirements)
    threshold = int(parameters.get("threshold", 10000))
    approval_levels = int(parameters.get("approval_levels", 2))
    document_types = parameters.get("document_types", ["ap_invoice"])
    rules = []
    if threshold > 1000:
        rules.append({"document_type": "ap_invoice", "amount_threshold": 1000, "approval_levels_required": 0})
        rules.append({"document_type": "ap_invoice", "amount_threshold": threshold, "approval_levels_required": 1})
    for document_type in document_types:
        rules.append({"document_type": document_type, "amount_threshold": threshold, "approval_levels_required": approval_levels})
    rules.append({"document_type": "purchase_order", "amount_threshold": 50000, "approval_levels_required": 1})
    return rules


def _cost_center_code(name: str) -> str:
    parts = [part[:1] for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    if parts:
        code = "".join(parts).upper()
    else:
        code = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:5]
    return (code or "CC")[:5]


def _currency_name(code: str) -> str:
    names = {"USD": "US Dollar", "EUR": "Euro", "GBP": "British Pound"}
    return names.get(code, code)


def _sample_vendors() -> list[dict[str, Any]]:
    vendor_names = ["Acme Supplies", "Global Parts Co", "Premium Materials", "Tech Solutions Inc", "Office Essentials"]
    return [
        {
            "vendor_number": f"VEN{index + 1:03d}",
            "name": name,
            "email": f"contact@{re.sub(r'[^a-z0-9]+', '', name.lower())}.example.com",
            "tax_id": f"{10 + index:02d}-{3456789 + index}",
            "payment_terms_days": [30, 45, 60][index % 3],
            "is_active": True,
        }
        for index, name in enumerate(vendor_names)
    ]


def _sample_customers() -> list[dict[str, Any]]:
    customer_names = ["ABC Corporation", "XYZ Industries", "Global Enterprises", "Tech Startups Inc", "Manufacturing Co"]
    credit_limits = [100000.00, 250000.00, 500000.00, 75000.00, 300000.00]
    return [
        {
            "customer_number": f"CUS{index + 1:03d}",
            "name": name,
            "email": f"contact@{re.sub(r'[^a-z0-9]+', '', name.lower())}.example.com",
            "credit_limit": credit_limits[index],
            "payment_terms_days": [30, 45, 60][index % 3],
            "is_active": True,
        }
        for index, name in enumerate(customer_names)
    ]


class AutoERPAgentSuite:
    def __init__(self, llm_client: GeminiClient | None = None, persistence: StatePersistence | None = None) -> None:
        shared_llm = llm_client or GeminiClient()
        shared_persistence = persistence or StatePersistence()
        self.requirement_parser = RequirementParserAgent(shared_llm, shared_persistence)
        self.schema_designer = SchemaDesignerAgent(shared_llm, shared_persistence)
        self.code_generator = CodeGeneratorAgent(shared_llm, shared_persistence)
        self.config_generator = ConfigGeneratorAgent(shared_persistence)
        self.master_data_initializer = MasterDataInitializerAgent(shared_persistence)


def _fallback_requirements(requirements_input: str) -> list[dict[str, Any]]:
    lowered = requirements_input.lower()
    requirements: list[dict[str, Any]] = []

    cost_centers_match = re.search(r"cost centers?\s*:\s*([^.\\n]+)", requirements_input, re.IGNORECASE)
    if cost_centers_match:
        cost_centers = [part.strip() for part in cost_centers_match.group(1).split(",") if part.strip()]
        if cost_centers:
            requirements.append(
                {
                    "type": "ACCOUNTING_STRUCTURE",
                    "description": "Configure chart of accounts and cost center structure.",
                    "priority": 5,
                    "parameters": {"cost_centers": cost_centers, "structure_type": "standard_financial_erp"},
                    "confidence_score": 0.92,
                }
            )

    currencies: list[str] = []
    currency_match = re.search(r"multi-currency(?:\s+support)?\s+([^.\\n]+)", requirements_input, re.IGNORECASE)
    if currency_match:
        for part in re.split(r"[,/ ]+", currency_match.group(1)):
            code = part.strip().upper()
            if code in VALID_CURRENCY_CODES and code not in currencies:
                currencies.append(code)
    if not currencies:
        currencies = [code for code in VALID_CURRENCY_CODES if re.search(rf"\b{code}\b", requirements_input, re.IGNORECASE)]
    if currencies:
        requirements.append(
            {
                "type": "CURRENCY",
                "description": f"Support multi-currency processing for {', '.join(currencies)}.",
                "priority": 4,
                "parameters": {"currencies": currencies, "base_currency": currencies[0]},
                "confidence_score": 0.95,
            }
        )

    threshold_match = re.search(r"(?:over|above|greater than|>)\s*\$?\s*(\d+(?:,\d{3})*|\d+)\s*([kK]?)", requirements_input)
    if threshold_match:
        threshold = int(threshold_match.group(1).replace(",", ""))
        if threshold_match.group(2):
            threshold *= 1000
        requirements.append(
            {
                "type": "APPROVAL_WORKFLOW",
                "description": f"Approval workflow required for invoices over {threshold}.",
                "priority": 5,
                "parameters": {"threshold": threshold, "approval_levels": 2, "document_types": ["ap_invoice"]},
                "confidence_score": 0.9,
            }
        )

    if "report" in lowered or "trial balance" in lowered:
        requirements.append(
            {
                "type": "REPORT",
                "description": "Provide standard financial reporting.",
                "priority": 3,
                "parameters": {"reports": ["trial_balance", "balance_sheet", "income_statement"], "frequency": "on_demand"},
                "confidence_score": 0.8,
            }
        )

    return requirements


def _fallback_schema(company_name: str, requirements: list[Requirement]) -> dict[str, Any]:
    currencies = _extract_currencies(requirements)
    include_cost_centers = any(req.type == "ACCOUNTING_STRUCTURE" for req in requirements)
    include_approvals = any(req.type == "APPROVAL_WORKFLOW" for req in requirements)
    tables = [
        {
            "name": "gl_accounts",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "account_number", "type": "varchar(20)", "nullable": False, "unique": True},
                {"name": "account_name", "type": "varchar(255)", "nullable": False},
                {"name": "account_type", "type": "varchar(20)", "nullable": False},
                {"name": "parent_account_id", "type": "uuid", "nullable": True},
                {"name": "balance", "type": "decimal(15,2)", "nullable": False, "default": "0"},
            ],
            "indexes": ["account_number", "account_type", "parent_account_id"],
        },
        {
            "name": "cost_centers",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "code", "type": "varchar(10)", "nullable": False, "unique": True},
                {"name": "name", "type": "varchar(255)", "nullable": False},
            ],
            "indexes": ["code"],
        },
        {
            "name": "currencies",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "code", "type": "varchar(3)", "nullable": False, "unique": True},
                {"name": "exchange_rate_to_base", "type": "decimal(15,6)", "nullable": False},
            ],
            "indexes": ["code"],
        },
        {
            "name": "ap_invoices",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "invoice_number", "type": "varchar(50)", "nullable": False},
                {"name": "vendor_id", "type": "uuid", "nullable": False},
                {"name": "amount", "type": "decimal(15,2)", "nullable": False},
                {"name": "currency", "type": "varchar(3)", "nullable": False, "default": currencies[0]},
                {"name": "approval_status", "type": "varchar(20)", "nullable": False, "default": "PENDING"},
            ],
            "indexes": ["vendor_id", "invoice_number", "status", "due_date"],
        },
        {
            "name": "journal_entries",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "journal_batch_id", "type": "varchar(50)", "nullable": False},
                {"name": "account_id", "type": "uuid", "nullable": False},
                {"name": "debit", "type": "decimal(15,2)", "nullable": False, "default": "0"},
                {"name": "credit", "type": "decimal(15,2)", "nullable": False, "default": "0"},
            ],
            "indexes": ["journal_batch_id", "account_id", "journal_date"],
        },
        {
            "name": "vendors",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "vendor_number", "type": "varchar(20)", "nullable": False, "unique": True},
                {"name": "vendor_name", "type": "varchar(255)", "nullable": False},
            ],
            "indexes": ["vendor_number"],
        },
        {
            "name": "customers",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "customer_number", "type": "varchar(20)", "nullable": False, "unique": True},
                {"name": "customer_name", "type": "varchar(255)", "nullable": False},
            ],
            "indexes": ["customer_number"],
        },
        {
            "name": "audit_log",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "table_name", "type": "varchar(100)", "nullable": False},
                {"name": "record_id", "type": "uuid", "nullable": False},
                {"name": "action", "type": "varchar(20)", "nullable": False},
            ],
            "indexes": ["table_name", "record_id"],
        },
        {
            "name": "approval_workflows",
            "columns": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "document_type", "type": "varchar(50)", "nullable": False},
                {"name": "amount_threshold", "type": "decimal(15,2)", "nullable": False},
                {"name": "approval_levels_required", "type": "integer", "nullable": False},
            ],
            "indexes": ["document_type"],
        },
    ]
    relationships = [
        {"from_table": "gl_accounts", "to_table": "cost_centers", "column": "cost_center_id", "target_column": "id"},
        {"from_table": "gl_accounts", "to_table": "gl_accounts", "column": "parent_account_id", "target_column": "id"},
        {"from_table": "ap_invoices", "to_table": "vendors", "column": "vendor_id", "target_column": "id"},
        {"from_table": "journal_entries", "to_table": "gl_accounts", "column": "account_id", "target_column": "id"},
    ]
    if not include_cost_centers:
        relationships = [rel for rel in relationships if rel["to_table"] != "cost_centers"]
    return {
        "company": company_name or "Generated ERP",
        "tables": tables,
        "enums": ["account_type", "ap_invoice_status", "approval_status", "journal_entry_status"],
        "constraints": [
            "journal_entries.debit >= 0",
            "journal_entries.credit >= 0",
            "ap_invoices.amount > 0",
        ],
        "relationships": relationships,
        "notes": [
            "Generated in local mock mode for Gemini-free-tier testing.",
            f"Currency support prepared for: {', '.join(currencies)}",
            "Approval workflows included." if include_approvals else "Approval workflows available with defaults.",
        ],
    }


def _fallback_code_files(company_name: str, requirements: list[Requirement]) -> dict[str, str]:
    app_name = company_name or "Generated ERP"
    currencies = _extract_currencies(requirements)
    return {
        "models.py": f'''"""SQLAlchemy models for {app_name}."""\n\nfrom sqlalchemy.orm import DeclarativeBase\n\n\nclass Base(DeclarativeBase):\n    pass\n''',
        "schemas.py": f'''"""Pydantic schemas for {app_name}."""\n\nfrom pydantic import BaseModel\n\n\nclass HealthResponse(BaseModel):\n    status: str = "healthy"\n''',
        "routes.py": '''"""FastAPI routes for generated ERP modules."""\n\nfrom fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n@router.get("/health")\ndef health() -> dict[str, str]:\n    return {"status": "healthy"}\n''',
        "database.py": '''"""Database bootstrap for generated ERP project."""\n\nfrom sqlalchemy import create_engine\nfrom sqlalchemy.orm import sessionmaker\n\nDATABASE_URL = "postgresql://erp_user:change_me@db:5432/erp_db"\nengine = create_engine(DATABASE_URL)\nSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)\n''',
        "main.py": f'''"""Generated FastAPI entrypoint for {app_name}."""\n\nfrom fastapi import FastAPI\n\nfrom routes import router\n\napp = FastAPI(title="{app_name}")\napp.include_router(router)\n\n\n@app.get("/")\ndef root() -> dict[str, object]:\n    return {{"message": "Generated ERP starter app", "currencies": {currencies!r}}}\n''',
    }
