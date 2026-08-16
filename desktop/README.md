# QAgent Pet Desktop

Electron 桌面客户端。开发模式可以连接源码后端，正式打包时会通过 PyInstaller 内置独立后端，普通用户不需要安装 Python 或 Node.js。

## 功能

- 透明、无边框、置顶桌宠窗口。
- 桌宠图片可拖拽移动；点击桌宠或 2 字气泡打开轻聊天窗口。
- 轻聊天窗口调用现有 FastAPI 后端聊天接口，展示思考态与回复。
- 桌面提醒气泡只显示低敏 2 字概括，例如“找你”“想你”“等待”“困了”。完整消息只在轻聊天或 Web 面板中查看。
- 勿扰模式下不弹出主动气泡。
- 托盘/右键菜单支持显示桌宠、打开完整 Web 面板、切换勿扰、切换预设宠物、退出。
- 启动时检测 `8080` / `10000` 后端端口；未发现时尝试在项目根目录执行 `python main.py` 自动拉起后端。
- 桌宠与 Web 面板通过 Electron `userData/config.json` 共用 `user_id/session_id/pet_type`，从而共用同一后端会话与记忆。
- 首次启动提供 AI 服务配置窗口，API Key 写入 Electron 用户数据目录的 `runtime.env`。
- 数据库、配置和日志统一保存在 Electron `userData`，应用升级不会覆盖用户数据。
- 从源码版首次迁移时，会使用 SQLite backup 将项目根目录旧数据库复制到用户数据目录。

## 开发运行

```bash
cd desktop
npm install
npm start
```

开发模式优先读取项目根目录 `.env`；如果用户通过桌面设置保存过配置，则优先读取用户目录的 `runtime.env`。桌宠会自动选择项目 `.venv` 中的 Python 并启动后端。

## 构建安装包

先安装运行依赖、打包依赖和 Electron 依赖：

```bash
python -m pip install -r requirements-build.txt
cd desktop
npm install
```

然后在目标操作系统上构建：

```bash
cd desktop
npm run dist
```

构建过程先通过 PyInstaller 在 `desktop/backend-dist/qagent-backend/` 生成当前平台的独立后端，再由 `electron-builder` 将 Electron、前端资源和后端组合成安装产物。

构建时会先运行 `scripts/build-icons.py`，以项目根目录的 `logo.png` 生成 macOS、Windows 和 Linux 所需的产品图标。更换 Logo 后重新执行构建即可同步更新安装包图标。

输出目录为 `desktop/dist/`：Windows 生成 NSIS/portable，macOS 生成 DMG/ZIP，Linux 生成 AppImage。安装包必须在对应目标操作系统上构建；正式公开发布前仍需配置代码签名、macOS notarization 和自动更新服务。

只验证解包后的应用目录时可运行：

```bash
npm run dist:dir
```

## 用户数据

运行时文件位于 Electron 的系统 `userData` 目录：

- `runtime.env`：LLM 地址、模型和 API Key。
- `qagent_pet.db`：对话、记忆、画像、关系和学习数据。
- `backups/`：每天最多一份 SQLite 一致性备份，自动保留最近 5 份。
- `config.json`：桌宠、会话、勿扰等非敏感客户端状态。
- `backend.log` / `backend_err.log`：本地核心运行日志。

用户可以从托盘菜单或 Web 设置页直接打开该目录。

## 隐私边界

MVP 只使用以下低敏信号触发气泡：

- 当前时间段；
- 后端返回的宠物状态；
- 距离上次互动时间；
- 勿扰模式状态。

不读取屏幕内容、窗口标题、聊天软件内容或其他敏感应用数据。
