#!/usr/bin/env bash
set -euo pipefail

COMPOSE_CMD=${COMPOSE_CMD:-"docker compose"}
POSTGRES_SERVICE=${POSTGRES_SERVICE:-postgres}
CHROMA_SERVICE=${CHROMA_SERVICE:-chromadb}
REDIS_SERVICE=${REDIS_SERVICE:-redis}
BACKEND_SERVICE=${BACKEND_SERVICE:-backend}
FRONTEND_SERVICE=${FRONTEND_SERVICE:-frontend}

wait_for_postgres() {
  echo "Waiting for PostgreSQL to become ready..."
  until ${COMPOSE_CMD} exec -T "${POSTGRES_SERVICE}" pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ai_erp}" >/dev/null 2>&1; do
    sleep 2
  done
}

wait_for_chroma() {
  echo "Waiting for ChromaDB to become ready..."
  until curl --silent --fail "http://localhost:${CHROMA_PORT:-8001}/api/v1/heartbeat" >/dev/null 2>&1 || \
        curl --silent --fail "http://localhost:${CHROMA_PORT:-8001}/api/v2/heartbeat" >/dev/null 2>&1; do
    sleep 2
  done
}

run_migrations() {
  echo "Running database migrations..."
  if [ -f "backend/alembic.ini" ]; then
    ${COMPOSE_CMD} run --rm "${BACKEND_SERVICE}" alembic upgrade head
  else
    echo "No Alembic configuration found. Skipping migrations."
  fi
}

initialize_chroma() {
  echo "Validating ChromaDB connectivity..."
  ${COMPOSE_CMD} run --rm "${BACKEND_SERVICE}" python -c "import httpx, os; base=f'http://{os.getenv(\"CHROMA_HOST\", \"chromadb\")}:{os.getenv(\"CHROMA_PORT\", \"8001\")}'; ok=False
for path in ('/api/v1/heartbeat', '/api/v2/heartbeat'):
    try:
        response = httpx.get(f'{base}{path}', timeout=5.0)
        response.raise_for_status()
        ok = True
        break
    except Exception:
        pass
raise SystemExit(0 if ok else 1)"
}

echo "Starting infrastructure services..."
${COMPOSE_CMD} up -d "${POSTGRES_SERVICE}" "${CHROMA_SERVICE}" "${REDIS_SERVICE}"

wait_for_postgres
wait_for_chroma
run_migrations
initialize_chroma

echo "Starting application services..."
${COMPOSE_CMD} up -d "${BACKEND_SERVICE}" "${FRONTEND_SERVICE}"

echo "All services started."
