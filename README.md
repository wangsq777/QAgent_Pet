# QAgent Pet

一只常驻桌面的 AI 桌宠：透明置顶小窗 + 轻聊天 + 控制中心（Web 面板）+ 摸鱼中心（小说阅读 / 视频小窗）。**纯桌面应用**：后端为本地 FastAPI 服务，默认只监听本机回环地址，不对外提供公网入口。

## 功能

- **桌宠**：透明、无边框、置顶小窗（152×176），可拖拽移动；左键拖拽、点击打开聊天、右键呼出菜单；预设多款宠物皮肤；支持勿扰模式。
- **轻聊天**：调用 LLM（默认 MiniMax-M2.5）完成对话，展示思考态与回复；会话与记忆按用户身份持久化。
- **控制中心（Web 面板）**：随桌宠本地打包加载，统一管理聊天、陪学、摸鱼与设置。
- **摸鱼中心**
  - **小说阅读**：内置书架 + 用户导入 TXT / EPUB / DOCX，自动分章、记忆阅读进度；可在桌宠隐蔽阅读窗（透明置顶小窗）中继续读，支持不透明度调节。
  - **摸鱼·视频小窗**：嵌入式浏览器加载 **B 站 / 小红书 / 抖音**网页版，置顶小窗刷视频；浮条含后退/前进/刷新/缩放/置顶/收起/关闭，导航栏一键切换平台；自动隐藏「打开App」横幅；关闭即销毁窗口、停止后台播放。
- **开源安全**：视频小窗只做「嵌平台网页 + 客户端隐藏提示」，等同用户正常浏览，不调用平台非官方接口、不抓取数据。

## 技术栈与架构

| 层 | 技术 |
| --- | --- |
| 桌面端 | Electron（多窗口：桌宠 / 聊天 / 小说 / 视频小窗 / 设置 / 控制中心） |
| 后端 | Python 3.9 · FastAPI（本地 `127.0.0.1:10000`，桌面端自动拉起） |
| 前端 | 原生 HTML / CSS / JS（控制中心面板） |
| 存储 | SQLite（对话、记忆、画像、关系、学习、小说等） |

纯桌面端：后端仅监听回环地址，不给局域网 / 公网开放。

## 项目结构

```text
.
├── main.py                  # 后端入口（FastAPI）
├── backend/
│   ├── routers/             # API 路由（会话/聊天/陪学/摸鱼/自定义宠物等）
│   └── services/            # 业务服务（LLM、记忆、情绪、小说导入/存储等）
├── desktop/
│   ├── main.js              # Electron 主进程（窗口/托盘/后端拉起）
│   ├── preload*.js          # 沙箱 preload（IPC 桥）
│   ├── feed_preload.js      # 视频小窗浮条/导航/「打开App」提示隐藏
│   └── renderer/            # 桌宠/聊天/小说/设置页面
├── frontend/                # 控制中心 Web 面板
├── requirements.txt
└── start.sh                 # 一键启动（fnm + .venv Python + npm start）
```

## 快速开始

需要 Node.js 与 Python 3.9+。

```bash
# 1. 配置环境变量（必填 LLM_API_KEY）
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY（默认 MiniMax-M2.5，获取：https://platform.minimaxi.chat/）

# 2. 安装依赖
pip install -r requirements.txt
cd desktop && npm install && cd ..

# 3. 一键启动（桌面端会自动拉起本地后端）
./start.sh
```

> 首次启动若未配置 API Key，会弹出 AI 服务设置窗口；填写后保存到 Electron 用户数据目录的 `runtime.env`，优先于项目根目录 `.env`。

## 配置

环境变量详见 `.env.example`：

- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`：LLM 服务（默认 MiniMax-M2.5）。
- `PORT`：后端端口（默认 10000）。
- `DATABASE_URL`：SQLite 数据库路径。
- `API_KEY`：接口认证，留空为开发模式。
- `WEATHER_API_KEY`：天气查询（可选）。

## 数据与隐私

运行时数据保存在 Electron 系统 `userData` 目录：

- `runtime.env`：LLM 地址、模型与 API Key。
- `qagent_pet.db`：对话、记忆、画像、关系、学习与小说数据。
- `backups/`：每日 SQLite 一致性备份，自动保留最近 5 份。
- `config.json`：桌宠、会话、勿扰等客户端状态。
- `backend.log` / `backend_err.log`：本地运行日志。

可从托盘菜单或设置页直接打开该目录。桌宠只使用低敏信号（时间段、宠物状态、距上次互动、勿扰状态）触发气泡，不读取屏幕、窗口标题或聊天软件内容。

## 常用命令

```bash
./start.sh                    # 一键启动
cd desktop && npm start       # 仅启动桌面端
cd desktop && npm run dist    # 打包安装包（含内置后端）
```
