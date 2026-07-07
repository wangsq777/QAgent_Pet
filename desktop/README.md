# QAgent Pet Desktop MVP

Electron 桌宠 MVP，用于验证“桌面常驻 + 轻气泡 + 轻聊天 + 打开 Web 面板”的 Phase 2 闭环。

## 功能

- 透明、无边框、置顶桌宠窗口。
- 桌宠图片可拖拽移动；点击桌宠或 2 字气泡打开轻聊天窗口。
- 轻聊天窗口调用现有 FastAPI 后端聊天接口，展示思考态与回复。
- 桌面提醒气泡只显示低敏 2 字概括，例如“找你”“想你”“等待”“困了”。完整消息只在轻聊天或 Web 面板中查看。
- 勿扰模式下不弹出主动气泡。
- 托盘/右键菜单支持显示桌宠、打开完整 Web 面板、切换勿扰、切换预设宠物、退出。
- 启动时检测 `8080` / `10000` 后端端口；未发现时尝试在项目根目录执行 `python main.py` 自动拉起后端。
- 桌宠与 Web 面板通过 Electron `userData/config.json` 共用 `user_id/session_id/pet_type`，从而共用同一后端会话与记忆。

## 开发运行

```bash
cd desktop
npm install
npm start
```

> 后端默认从项目根目录 `.env` 读取配置。当前项目可使用 `PORT=8080`，如果后端未启动，桌宠会尝试自动执行 `python main.py`。

## 打包目标

```bash
cd desktop
npm run dist
```

`electron-builder` 会按 `package.json` 的 `build` 配置输出 Windows `nsis` 安装包与 `portable` 可执行程序。MVP 阶段先验证工程组织与运行闭环，正式发布前还需要补充图标、签名、后端依赖打包和安装后自检。

## 隐私边界

MVP 只使用以下低敏信号触发气泡：

- 当前时间段；
- 后端返回的宠物状态；
- 距离上次互动时间；
- 勿扰模式状态。

不读取屏幕内容、窗口标题、聊天软件内容或其他敏感应用数据。
