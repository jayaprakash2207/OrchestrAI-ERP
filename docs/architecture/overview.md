# Architecture Overview

## Core Domains

- `AutoERP Generator`: requirement intake, planning, module generation, workflow assembly
- `JD Edwards AI Copilot`: retrieval, chat orchestration, enterprise context, task assistance
- `Platform Services`: identity, observability, persistence, vector storage, workflow execution

## Backend Layers

- `app/api/` HTTP routes and request handling
- `app/services/ai/` Gemini model adapters and prompt execution
- `app/services/orchestration/` LangGraph workflows and agents
- `app/repositories/` persistence abstraction
- `app/models/` SQLAlchemy entities
- `app/schemas/` API contracts

## Frontend Layers

- `src/app/` route structure and page composition
- `src/components/` reusable UI building blocks
- `src/lib/` API clients and browser utilities
- `src/styles/` global design foundation
