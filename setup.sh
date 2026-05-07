#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install it from https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is not available. See https://docs.docker.com/compose/install/"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env created from .env.example. Review values before production use."
fi

docker compose build
docker compose up -d postgres

until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ai_erp}" >/dev/null 2>&1; do
  echo "Waiting for database..."
  sleep 2
done

docker compose up -d backend
docker compose exec backend alembic upgrade head || echo "Migrations skipped or failed. Review logs before continuing."
docker compose up -d chromadb frontend

echo "API: http://localhost:8000"
echo "Docs: http://localhost:8000/docs"
echo "Frontend: http://localhost:3000"
