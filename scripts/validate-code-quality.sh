#!/usr/bin/env bash
# 文件职责：串行执行后端 lint、类型检查、测试以及前端构建验证。

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_VENV="$ROOT_DIR/backend/.venv/bin"
FRONTEND_BIN="$ROOT_DIR/frontend/node_modules/.bin"

require_executable() {
  local executable=$1
  local setup_hint=$2
  if [[ ! -x "$executable" ]]; then
    printf 'FAIL  missing executable: %s\n' "$executable" >&2
    printf '      %s\n' "$setup_hint" >&2
    exit 1
  fi
}

require_executable "$BACKEND_VENV/ruff" "Install backend development dependencies in backend/.venv."
require_executable "$BACKEND_VENV/mypy" "Install backend development dependencies in backend/.venv."
require_executable "$BACKEND_VENV/pytest" "Install backend development dependencies in backend/.venv."
require_executable "$FRONTEND_BIN/tsc" "Install frontend dependencies before running the quality gate."
require_executable "$FRONTEND_BIN/eslint" "Install frontend dependencies before running the quality gate."
require_executable "$FRONTEND_BIN/next" "Install frontend dependencies before running the quality gate."

printf 'MerchPilot code quality gate\n\n'

"$ROOT_DIR/scripts/validate-comments.sh"
printf 'PASS  source comments coverage\n'

cd "$ROOT_DIR/backend"
"$BACKEND_VENV/ruff" check src tests
printf 'PASS  backend Ruff\n'
"$BACKEND_VENV/mypy" src
printf 'PASS  backend strict Mypy\n'
"$BACKEND_VENV/pytest" -q -m 'not integration'
printf 'PASS  backend non-integration tests\n'

cd "$ROOT_DIR/frontend"
"$FRONTEND_BIN/tsc" --noEmit
printf 'PASS  frontend TypeScript\n'
"$FRONTEND_BIN/eslint" .
printf 'PASS  frontend ESLint\n'
"$FRONTEND_BIN/next" build --webpack
printf 'PASS  frontend production build\n'

printf '\nCode quality gate passed.\n'
