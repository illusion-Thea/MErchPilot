# 文件职责：为本地开发者提供统一的启动、检查、测试和服务管理命令入口。

.PHONY: setup up dev down logs migrate rebuild-hybrid-index test-backend lint-backend typecheck-backend typecheck-web lint-web build-web quality comments courseware models integration validate-local mcp prepare-low-memory-model

setup:
	cp .env.example .env

up:
	docker compose up --build

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker-planning worker-index worker-report web

migrate:
	docker compose run --rm migrate

rebuild-hybrid-index:
	docker compose exec api python -m merchpilot.rebuild_hybrid_index

models:
	docker compose up --build embedding-service reranker-service

# 将单个本地 FP32 模型转换为 BF16 safetensors 分片；SOURCE_MODEL 与 TARGET_MODEL 由调用方提供。
prepare-low-memory-model:
	test -n "$(SOURCE_MODEL)" && test -n "$(TARGET_MODEL)"
	docker run --rm -v "$(SOURCE_MODEL):/source:ro" -v "$(TARGET_MODEL):/output" -v "$(CURDIR)/scripts:/scripts:ro" merchpilot-embedding-service python /scripts/prepare-low-memory-model.py /source /output --max-shard-size "$${MAX_SHARD_SIZE:-600MB}"

mcp:
	docker compose build mcp
	docker compose up -d --no-deps mcp

integration:
	./scripts/run-integration-tests.sh

validate-local:
	./scripts/validate-local.sh

test-backend:
	docker compose run --rm api pytest

lint-backend:
	docker compose run --rm api ruff check src tests

typecheck-backend:
	cd backend && .venv/bin/mypy src

typecheck-web:
	docker compose run --rm web pnpm typecheck

lint-web:
	docker compose run --rm web pnpm lint

build-web:
	docker compose run --rm web pnpm build

quality:
	./scripts/validate-code-quality.sh

comments:
	./scripts/validate-comments.sh

courseware:
	node scripts/validate-courseware.mjs
