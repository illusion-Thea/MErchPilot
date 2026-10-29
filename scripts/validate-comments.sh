#!/usr/bin/env bash
# 文件职责：检查一方源码是否具有中文文件职责说明，防止后续新增代码失去阅读入口。

set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

missing=0

# Python 使用模块文档字符串；前端和脚本使用适合各自语法的文件头注释。
while IFS= read -r file; do
  if ! sed -n '1,8p' "$file" | grep -q '文件职责'; then
    printf '缺少文件职责说明: %s\n' "$file"
    missing=1
  fi
done < <(find backend/src/merchpilot backend/alembic backend/tests -type f -name '*.py' | sort)

while IFS= read -r file; do
  if ! sed -n '1,10p' "$file" | grep -q '文件职责'; then
    printf '缺少文件职责说明: %s\n' "$file"
    missing=1
  fi
done < <(find frontend/src -type f \( -name '*.ts' -o -name '*.tsx' \) | sort)

while IFS= read -r file; do
  if ! sed -n '1,8p' "$file" | grep -q '文件职责'; then
    printf '缺少文件职责说明: %s\n' "$file"
    missing=1
  fi
done < <(find scripts -type f -name '*.sh' | sort)

# 可写注释的部署、样式和工具配置也必须有阅读入口；JSON 与锁文件除外。
for file in \
  .env.example \
  Makefile \
  docker-compose.yml \
  docker-compose.dev.yml \
  backend/Dockerfile \
  backend/Dockerfile.mcp \
  backend/Dockerfile.model \
  backend/pyproject.toml \
  backend/alembic.ini \
  frontend/Dockerfile \
  frontend/next.config.ts \
  frontend/eslint.config.mjs \
  frontend/pnpm-workspace.yaml \
  frontend/src/app/globals.css \
  backend/alembic/script.py.mako \
  .workbook/build_optimized_workbook.mjs \
  .workbook/build_workbook.mjs \
  .workbook/collect_audapi.mjs \
  .workbook/collect_brunei_official.mjs \
  .workbook/collect_parker_data.mjs \
  .workbook/inspect.mjs \
  .workbook/verify_optimized_render.mjs \
  .workbook/verify_render.mjs; do
  if ! sed -n '1,10p' "$file" | grep -q '文件职责'; then
    printf '缺少文件职责说明: %s\n' "$file"
    missing=1
  fi
done

# Python AST 检查比文本搜索更可靠，可识别类、同步函数和异步函数的真实文档串。
python_runtime=backend/.venv/bin/python
if [[ ! -x "$python_runtime" ]]; then
  python_runtime=python3
fi
if ! "$python_runtime" - <<'PY'
import ast
from pathlib import Path

missing: list[str] = []
for root in (Path("backend/src/merchpilot"), Path("backend/tests")):
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if ast.get_docstring(node) is None:
                missing.append(f"{path}:{node.lineno} {node.name}")

if missing:
    print("以下 Python 类或函数缺少文档串：")
    print("\n".join(missing))
    raise SystemExit(1)

print("PASS  Python 类和函数均包含文档串")
PY
then
  missing=1
fi

if [[ -x frontend/node_modules/.bin/tsc ]]; then
  if ! node scripts/validate-comment-coverage.mjs; then
    missing=1
  fi
else
  printf 'SKIP  前端声明 JSDoc 检查（尚未安装前端依赖）\n'
fi

if [[ $missing -ne 0 ]]; then
  exit 1
fi

printf 'PASS  所有一方源码均包含文件职责说明\n'
