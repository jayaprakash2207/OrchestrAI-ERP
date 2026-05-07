# AI ERP Platform Documentation

This repository contains an AI-powered ERP platform with two primary products:

- **AutoERP Generator**: Generates complete financial ERP solutions from natural language requirements.
- **JD Edwards AI Copilot**: Assists teams working with existing JD Edwards environments.

## Technology Stack

- **Backend**: FastAPI, LangGraph, ChromaDB, PostgreSQL
- **Frontend**: Next.js, React, TypeScript
- **AI**: Google Gemini API 2.0
- **Containers**: Docker, Docker Compose

## Repository Structure

- `backend/` — FastAPI application, domain services, orchestration, persistence, tests
- `frontend/` — Next.js application shell and shared UI
- `docs/` — Architecture, API, deployment, and product documentation
- `infra/` — Container assets and helper scripts

## Documentation Areas

- `docs/architecture/` — System design and component boundaries
- `docs/api/` — HTTP contract notes
- `docs/deployment/` — Local and production rollout guides
- `docs/product/` — Roadmap, domain assumptions, and feature planning

## Quick Start

1. Copy `.env.example` to `.env` and fill in secrets.
2. Start infrastructure with `docker compose up --build`.
3. Run backend locally from `backend/`.
4. Run frontend locally from `frontend/`.
