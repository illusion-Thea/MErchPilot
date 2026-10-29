#!/usr/bin/env bash
# 文件职责：创建隔离的 PostgreSQL 集成测试库，执行迁移和租户边界测试。

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
POSTGRES_USER=${POSTGRES_USER:-merchpilot}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-merchpilot}
TEST_DATABASE_URL=${TEST_DATABASE_URL:-postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/merchpilot_test}

cd "$ROOT_DIR"
docker compose up -d postgres

for attempt in {1..60}; do
  if docker compose exec -T postgres pg_isready \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB:-merchpilot}" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == "60" ]]; then
    docker compose logs --tail=100 postgres
    exit 1
  fi
  sleep 1
done

if ! docker compose exec -T postgres psql \
  -U "${POSTGRES_USER}" \
  -d postgres \
  -tAc "SELECT 1 FROM pg_database WHERE datname = 'merchpilot_test'" | grep -q 1; then
  docker compose exec -T postgres createdb -U "${POSTGRES_USER}" merchpilot_test
fi

TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  "$ROOT_DIR/backend/.venv/bin/pytest" -q -m integration backend/tests/integration
