#!/bin/bash
# 一键启动 QAgent Pet：桌面端自动拉起本地后端，无需全局 node/npm。
# 双击运行；出错时窗口会停留并显示原因，不会一闪而过。

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# 后端使用的 Python（项目虚拟环境）
QAGENT_PYTHON="$PROJECT_ROOT/.venv/bin/python"

# Electron 可执行文件：直接用 desktop 本地依赖里自带的完整运行时，
# 不再经过 fnm/npm（旧写法依赖 fnm + npm start，环境变化后极易失效）。
ELECTRON_BIN="$PROJECT_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"

fail() {
  echo
  echo "❌ $1"
  echo
  read -r -p "按回车键关闭窗口…" _
  exit 1
}

[ -x "$QAGENT_PYTHON" ] || fail "未找到项目虚拟环境 Python：$QAGENT_PYTHON
请在项目根目录执行：
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt"

[ -x "$ELECTRON_BIN" ] || fail "未找到 Electron：$ELECTRON_BIN
请在 desktop/ 目录执行一次：
  npm install"

echo "正在启动 QAgent Pet…（本窗口可以关闭，退出应用请使用托盘菜单）"
exec "$ELECTRON_BIN" "$PROJECT_ROOT/desktop"
