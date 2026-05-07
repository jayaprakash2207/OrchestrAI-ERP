# OrchestrAI-ERP Project Documentation

## 1) Executive Summary
OrchestrAI-ERP is a monorepo for an AI-enabled ERP platform with two core products:

1. **AutoERP Generator** – generates ERP artifacts from natural-language requirements.
2. **JD Edwards AI Copilot** – provides guided Q&A and action execution patterns for JD Edwards workflows.

The platform combines a **FastAPI backend**, **Next.js frontend**, **PostgreSQL transactional store**, **ChromaDB vector store**, and **Redis cache**, with AI reasoning powered by **Google Gemini**.

---

## 2) Technology Stack
- **Backend:** FastAPI, Pydantic v2, SQLAlchemy, Alembic, LangGraph, Tenacity
- **Frontend:** Next.js 14, React 18, TypeScript
- **AI/LLM:** Google Gemini (`google-generativeai`)
- **Data Stores:** PostgreSQL, ChromaDB, Redis
- **Integration:** JD Edwards via REST/AIS orchestration or database connector (pyodbc)
- **Containerization:** Docker + Docker Compose

---

## 3) Repository Structure
- `backend/` – API, business logic, orchestration, models, schemas, tests
- `frontend/` – web UI (Pages Router active; App Router scaffold exists under `src/`)
- `docs/` – architecture/API/deployment/product notes
- `infra/docker/` – backend and frontend Dockerfiles
- `.env.example` – full runtime configuration template
- `docker-compose.yml` – local multi-service stack
- `setup.sh`, `start.sh` – local bootstrap/start helper scripts

---

## 4) System Architecture

### 4.1 High-level flow
1. User interacts with frontend pages (`/generator`, `/copilot`, `/studio`, `/jde-view`).
2. Frontend calls backend REST endpoints under `/api/v1/...`.
3. Backend routes requests through module endpoints (finance, supply chain, masters, AutoERP, Copilot).
4. Backend persists transactional data in PostgreSQL and checks health of ChromaDB/Redis/JDE.
5. AutoERP and Copilot services publish progress/messages via WebSocket channels.

### 4.2 Main backend entrypoint
- `backend/app/main.py`
- Registers middleware stack:
  - Request metrics
  - Rate limiting
  - Error tracking
  - Request ID propagation
  - JWT auth middleware (development bypass outside production)
  - CORS
- Exposes:
  - `GET /health`
  - `GET /metrics`
  - WebSockets:
    - `/ws/chat/{session_id}`
    - `/ws/generate/{generation_id}`

---

## 5) Backend Design

### 5.1 API routing
Primary versioned router: `backend/app/api/v1/router.py`

Included endpoint groups:
- `health`
- `autoerp`
- `copilot`
- `finance`
- `supply_chain`
- `masters`

### 5.2 Core domains

#### A) AutoERP Generator
- `POST /api/v1/autoerp/generate`
- `GET /api/v1/autoerp/generate/{generation_id}`
- `GET /api/v1/autoerp/generate/{generation_id}/download`

Runtime (`services/orchestration/runtime.py`) runs a 5-step pipeline:
1. Requirement parsing
2. Schema design
3. Code generation
4. Config generation
5. Master data initialization

Output is packaged as ZIP (generated code + configs + `schema.json` + `master_data.json`).

#### B) JD Edwards AI Copilot
- `POST /api/v1/copilot/chat`
- `POST /api/v1/copilot/execute`

`CopilotRuntime` routes prompt by module keywords (`finance`, `supply_chain`, `manufacturing`, `sales`, `hr`).
Execution mode creates a plan first and executes only when `confirm=true`.

#### C) Finance domain (major endpoints)
- GL Accounts: create/list/get/update/delete
- AP Invoices: create/list/get/approve/post/pay/void
- Journal: create/list/batch detail/validate/post/reverse
- Reports: trial balance, balance sheet, income statement, AP aging, AR aging, GL detail

#### D) Supply Chain domain
- Purchase orders: create/list/get/receive
- Inventory: list/adjust

#### E) Master data domain
- Vendors: list/create/get
- Customers: list/create
- Cost centers: list

### 5.3 Data model
Main SQLAlchemy entities in `backend/app/models/financial.py`:
- `GLAccount`, `CostCenter`
- `Vendor`, `Customer`
- `APInvoice`, `APInvoiceLineItem`, `APInvoiceApproval`
- `ARInvoice`
- `JournalEntry`
- `PurchaseOrder`, `PurchaseOrderLineItem`
- `InventoryItem`, `InventoryTransaction`
- `AuditLog`

Enums include account type, invoice status, approval status, PO status, journal status, inventory adjustment reason, and audit actions.

### 5.4 Configuration and runtime controls
- Centralized in `backend/app/core/config.py` (Pydantic settings)
- Supports:
  - environment profiles
  - DB pool tuning and retries
  - Gemini settings and token budgets
  - JDE connection mode (`api`, `database`, `hybrid`)
  - feature flags
  - rate limiting
  - Redis toggles

### 5.5 Integration layer
`backend/app/services/integrations/jde_connector.py`:
- `JDERestConnector`: REST/AIS orchestration calls, auth handling, retries, mapping
- `JDEDatabaseConnector`: read-only DB queries to JDE tables
- `JDEConnectorFactory`: connector selection by config

### 5.6 Reliability and observability
- Request ID + process-time headers
- Structured exception handlers with standardized payloads
- Rate limiting per client IP
- Health service checks: API, DB, Chroma, LLM, Redis, JDE
- Database manager with retry-enabled connectivity checks

---

## 6) Frontend Design

### 6.1 Active UI surface (Pages Router)
Primary user pages in `frontend/pages/`:
- `/` – product landing
- `/generator` – AutoERP generation UI with progress and artifact download
- `/copilot` – chat-based copilot interface
- `/studio` – combined functional studio (copilot + generation)
- `/jde-view` – workflow-style interactive JDE view
- `/api/jde-output` – reads latest generated ERP output from state folders

### 6.2 Frontend API client
`frontend/api/client.js` provides calls for:
- copilot chat/execute
- AutoERP generate/status/download URL
- WebSocket connectors for chat and generation progress

### 6.3 Secondary scaffold (App Router + TypeScript)
There is an additional starter UI under `frontend/src/` (`src/app`, `src/components`, `src/lib`) that is not the primary runtime route surface today, but indicates migration/scaffold direction.

---

## 7) AI and Orchestration Behavior

### 7.1 Gemini client
`backend/app/services/ai/gemini_client.py`:
- Retry with exponential backoff
- In-memory TTL cache
- token/cost estimation and budget tracking
- JSON extraction helper for model responses

### 7.2 AutoERP agents
`backend/app/services/orchestration/autoerp_agents.py` includes:
- `RequirementParserAgent`
- `SchemaDesignerAgent`
- `CodeGeneratorAgent`
- `ConfigGeneratorAgent`
- `MasterDataInitializerAgent`

It supports Gemini-powered generation with configurable fallback-to-mock behavior.

### 7.3 State persistence
`StatePersistence` stores orchestration state to JSON files at configured `STATE_STORAGE_PATH`.

---

## 8) Deployment and Operations

### 8.1 Docker Compose services
`docker-compose.yml` provisions:
- backend (port 8000)
- frontend (port 3000)
- postgres (5432)
- chromadb (host 8001 -> container 8000)
- redis (6379)

All services include health checks and share a bridge network.

### 8.2 Startup options
- `setup.sh`: build + staged startup + migration attempt
- `start.sh`: infra start, health waits, migration run, app start
- Manual: `docker compose up --build`

### 8.3 Environment setup
1. Copy `.env.example` to `.env`
2. Fill secrets (Gemini key, JWT secret, JDE values)
3. Start stack
4. Verify:
   - Backend: `http://localhost:8000`
   - API docs: `http://localhost:8000/docs`
   - Frontend: `http://localhost:3000`

---

## 9) Security and Controls
- JWT auth middleware for protected endpoints (development bypass allowed outside production)
- Sensitive config values redacted in startup logs
- Consistent error payload schema and request ID tracking
- Rate limit middleware enabled by configuration
- JDE database connector is read-only for safety

---

## 10) Testing and Validation Status (Current Repo)
Validated commands:
- Frontend:
  - `npm run lint` ✅
  - `npm run typecheck` ✅
  - `npm run build` ✅
- Backend:
  - `ENVIRONMENT=test python -m pytest` ✅ (1 test passed)

Observed notes:
- Backend currently has a minimal test suite (`app/tests/test_health.py`).
- Alembic environment exists; migration versions directory currently has no committed revisions.

---

## 11) Current State Assessment

### Strengths
- Clear modular backend structure and broad ERP domain coverage
- End-to-end AI workflow path already wired (request -> orchestration -> output)
- Good runtime configurability and health observability
- Dockerized local environment for reproducibility

### Gaps / Improvement opportunities
- Expand automated tests beyond health checks
- Add/commit full Alembic migration history
- Unify frontend architecture (Pages Router vs App Router scaffold) to reduce drift
- Add API/auth hardening validation for production deployment and CI checks

---

## 12) Conclusion
OrchestrAI-ERP is a functional AI-first ERP platform foundation with strong building blocks across ERP operations, AI orchestration, and JD Edwards integration. It is suitable for continued enterprise productization with next focus areas on testing depth, migration maturity, and frontend consolidation.
