#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$task_root"
task_python="$task_root/.venv/bin/python"

if [[ ! -x "$task_python" ]]; then
  echo '请先按 README 创建 .venv 并安装 Python 依赖。' >&2
  exit 1
fi
if ! "$task_python" -c 'import mdt_demo.api, uvicorn' >/dev/null 2>&1; then
  echo '缺少服务端依赖，请执行：.venv/bin/python -m pip install -e ".[api,dev]"' >&2
  exit 1
fi

# Rebuild installed frontend sources without downloading anything on startup.
if [[ -x frontend/node_modules/.bin/vite ]] && command -v npm >/dev/null 2>&1; then
  (cd frontend && npm run build)
elif [[ ! -f frontend/dist/index.html ]]; then
  echo '缺少前端构建，请执行：cd frontend && npm ci && npm run build' >&2
  exit 1
fi

echo 'MDT Lab 已准备就绪：http://127.0.0.1:8000'
echo '仅在本机运行；按 Ctrl+C 停止服务。'
exec "$task_python" -m uvicorn mdt_demo.api:app --host 127.0.0.1 --port 8000 --workers 1
