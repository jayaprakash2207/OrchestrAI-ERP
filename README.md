# AI ERP Platform

Monorepo scaffold for an AI-powered ERP platform with two flagship products:

- `AutoERP Generator`: generates complete financial ERP solutions from natural language requirements.
- `JD Edwards AI Copilot`: assists teams working with existing JD Edwards environments.

## Stack

- Backend: FastAPI, LangGraph, ChromaDB, PostgreSQL
- Frontend: Next.js, React, TypeScript
- AI: Google Gemini API 2.0
- Containers: Docker, Docker Compose

## Repository Layout

- `backend/` FastAPI application, domain services, orchestration, persistence, tests
- `frontend/` Next.js application shell and shared UI
- `docs/` architecture, API, deployment, and product documentation
- `infra/` container assets and helper scripts

## Quick Start

1. Copy `.env.example` to `.env` and fill in secrets.
2. Start infrastructure with `docker compose up --build`.
3. Run backend locally from `backend/`.
4. Run frontend locally from `frontend/`.

See [docs/architecture/overview.md](/c:/AI ERP/docs/architecture/overview.md) and [docs/deployment/local-development.md](/c:/AI ERP/docs/deployment/local-development.md) for more detail.
