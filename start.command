#!/bin/bash
# 一键启动 QAgent：后端 + 桌面端
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# 1. 激活 fnm，确保有 node/npm
export PATH="/Users/wangsiqin/.kimi-code/bin:$PATH"
eval "$(fnm env)"

# 2. 指定后端使用的 Python（项目虚拟环境）
export QAGENT_PYTHON="$PROJECT_ROOT/.venv/bin/python"

# 3. 启动桌面端（桌面端会自己检测/启动后端）
cd "$PROJECT_ROOT/desktop"
npm start
