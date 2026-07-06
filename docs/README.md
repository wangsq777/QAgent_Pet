# QAgent Pet - 个人 AI 电子宠物伴侣

QAgent Pet 是一个基于大语言模型的个人 AI 电子宠物伴侣系统。它不是单纯的一问一答聊天 Bot，而是围绕“关系型 AI 电子宠物”构建：宠物有稳定人格、长期记忆、情绪理解、主动关怀、亲密度成长、自定义角色、宠物串门和 GitHub 项目陪学能力。

当前项目形态是 **FastAPI 后端 + 原生 HTML/CSS/JavaScript Web 前端**。Web 端已完成桌面软件式宠物控制中心 MVP；下一阶段重点是 Electron / Tauri 桌宠 MVP，让宠物可以以独立桌面窗口常驻，而不是依赖浏览器页面。

---

## 当前定位

```text
QAgent Pet Core
AI 对话 / 宠物人格 / 记忆 / 情绪理解 / 亲密度 / 日程 / 学习 / 串门
        │
        ├── Web 端：完整功能中心（已实现 MVP）
        ├── 桌宠端：桌面常驻轻陪伴入口（下一阶段）
        └── QQ / IM / 移动端：远期可选扩展
```

产品差异化：通用 AI 助手更偏工具效率，QAgent Pet 更偏长期陪伴、人格连续性、主动关心和关系成长。

---

## 核心功能

### 1. 多宠物人格

- 预置宠物：Hot Dog、Cold Cat、鼠鼠。
- 每只宠物有独立人设、语气、主动关怀节奏和互动风格。
- 支持自定义宠物：名称、宠物类型、性格标签、口头禅、特殊习惯、头像。
- 自定义宠物开场白由 LLM 生成，并带 fallback 模板。

### 2. AI 聊天与情绪陪伴

- 主 LLM 输出结构化结果：`reply / emotion / need / intensity / risk_level`。
- 情绪和需求只作为后端内部信号，不在前端直接给用户贴标签。
- 情绪信号用于回复策略、亲密度、记忆压缩、主动关怀和高风险安全回应。
- 兼容 MiniMax thinking/text 多块响应，避免 thinking 块耗尽预算导致无正文。

### 3. 长期记忆与用户画像

- 短期上下文：最近对话消息。
- 长期记忆：话题变化后压缩摘要，写入 `long_term_memories`。
- 语义检索：Embedding 向量检索相关历史记忆。
- 用户画像：地区、身份、兴趣、职业、性格提示、活跃时段、情绪倾向等。

### 4. 主动关怀与轻养成

- 亲密度成长与关系等级。
- 日程自动提取与提醒。
- 天气查询与日常分享。
- 长时间未互动后的主动问候。
- Web 端宠物状态：`idle / happy / lonely / sleepy / studying`。
- 今日互动次数、陪伴时长、连续互动天数等轻养成数据。

### 5. 宠物串门

- 支持两只宠物围绕话题轮流对话。
- 用户可以插话。
- 串门结束后可生成摘要并沉淀为长期记忆。
- 已加入用户归属校验、限流、Prompt 注入过滤、消息数上限和删除宠物后的容错。

### 6. GitHub 项目陪学

- 输入 GitHub 公开仓库链接，生成学习大纲。
- 固定“源码导读老师 Agent”逐章讲解。
- 当前宠物作为陪学伙伴生成章末旁白。
- 支持向老师或宠物提问、章节完成奖励、全部完成奖励。
- 已加入 SSRF 防护、重定向禁用、路径穿越防护、仓库内容 Prompt 隔离、用户归属校验和限流。

### 7. Web 软件化与桌宠预览

- Web 主界面已从普通网页聊天页升级为桌面软件式 App Shell。
- 左侧固定导航、主内容区、右侧宠物状态 / 轻养成 / 学习入口。
- 新增设置页、勿扰模式本地开关、桌宠预览页。
- 桌宠预览使用图片 + CSS 动画展示未来透明置顶窗口和 2 字轻气泡方向。

---

## 技术栈

### 后端

- FastAPI
- SQLite + aiosqlite
- Pydantic
- httpx
- slowapi
- MiniMax / Anthropic Messages 兼容接口
- Open-Meteo 天气 API

### 前端

- 原生 HTML
- 原生 CSS
- 原生 JavaScript
- 无前端框架依赖

### 数据

- SQLite 本地数据库：`qagent_pet.db`
- 本地开发首次启动自动建表和迁移

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少配置：

```env
LLM_API_KEY=你的 API Key
LLM_BASE_URL=https://api.minimaxi.com/anthropic
LLM_MODEL=MiniMax-M2.5
PORT=10000
API_KEY=
CORS_ORIGINS=http://localhost:10000,http://127.0.0.1:10000
LOG_LEVEL=INFO
```

说明：

- `API_KEY` 为空时为开发模式，会跳过认证；生产环境必须设置强密码。
- `CORS_ORIGINS` 生产环境必须改成实际域名，不要使用 `*`。

### 3. 启动服务

```bash
python main.py
```

启动成功后访问：

```text
http://localhost:10000/
```

根路径会自动跳转到：

```text
/frontend/index.html
```

---

## 主要页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 首页 / 宠物选择 | `/frontend/index.html` | 选择预置宠物或进入自定义宠物 |
| 聊天主界面 | `/frontend/chat.html` | 桌面软件式宠物控制中心 |
| 自定义宠物 | `/frontend/custom_pet.html` | 创建和配置专属宠物 |
| 陪我学 | `/frontend/learn.html` | GitHub 项目陪学页面 |
| 桌宠预览 | `/frontend/desktop_pet.html` | 未来桌宠小窗口交互预览 |
| 设置中心 | `/frontend/settings.html` | 勿扰、托盘、通知、数据目录等桌面软件概念入口 |

---

## 主要 API 模块

| 模块 | 路由前缀 | 说明 |
|------|----------|------|
| 会话 / 记忆 / 状态 | `/api/sessions` | 创建会话、获取消息、记忆面板、宠物状态、模拟时间 |
| 聊天 | `/api/sessions/{session_id}/chat` | 主对话接口 |
| 自定义宠物 | `/api/custom-pets` | 自定义宠物 CRUD |
| 串门 | `/api/visits` | 宠物串门对话 |
| 陪学 | `/api/learning` | GitHub 仓库分析、学习会话、章节讲解、问答和奖励 |

---

## 当前项目结构

```text
QAgent_Pet/
├── main.py
├── requirements.txt
├── backend/
│   ├── auth.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── sessions.py
│   │   ├── chat.py
│   │   ├── custom_pets.py
│   │   ├── visits.py
│   │   └── learning.py
│   ├── services/
│   │   ├── llm_service.py
│   │   ├── memory_service.py
│   │   ├── embedding_service.py
│   │   ├── user_profile_agent.py
│   │   ├── mood_agent.py
│   │   ├── cross_pet_service.py
│   │   ├── learning_service.py
│   │   ├── github_service.py
│   │   ├── weather_service.py
│   │   └── tool_executor.py
│   └── prompts/
│       ├── hot_dog.py
│       ├── cold_cat.py
│       ├── mouse.py
│       └── custom_pet.py
├── frontend/
│   ├── index.html
│   ├── chat.html
│   ├── custom_pet.html
│   ├── learn.html
│   ├── desktop_pet.html
│   ├── settings.html
│   ├── css/
│   └── js/
└── docs/
    ├── README.md
    ├── plan.md
    ├── bug.md
    └── update.md
```

---

## 本地演示建议

推荐演示顺序：

1. 打开首页，展示 Hot Dog / Cold Cat / 鼠鼠和自定义宠物入口。
2. 进入 Hot Dog 聊天，发送普通消息和低落/焦虑消息，展示情绪陪伴和亲密度变化。
3. 发送包含日程的话，再点击模拟日程提醒。
4. 点击模拟隔天，展示主动关怀。
5. 打开记忆面板，展示长期记忆和用户画像。
6. 打开“陪我学”，输入 GitHub 公开仓库链接，展示学习大纲和章节讲解。
7. 打开桌宠预览页，说明下一阶段 Electron / Tauri 桌宠方向。

常见问题：

| 问题 | 处理 |
|------|------|
| 启动时报依赖缺失 | 重新运行 `pip install -r requirements.txt` |
| 发送消息无回复 | 检查 `LLM_API_KEY`、余额和网络 |
| 403 或会话异常 | 刷新页面或清理 localStorage 后重新选择宠物 |
| 端口被占用 | 修改 `.env` 中的 `PORT` |
| 数据想重置 | 停止服务后删除 `qagent_pet.db`，再重新启动 |

---

## 当前路线

当前已完成：

- Phase 0 情感捕捉细化
- Phase 1 Web 端电子宠物化 / 软件化 MVP

下一阶段优先：

- Phase 2 桌宠 MVP
  - 新增 Electron / Tauri 桌面壳
  - 自动连接或拉起本地后端
  - 主窗口加载现有 Web 功能中心
  - 桌宠小窗口透明、无边框、置顶、可拖拽
  - 点击宠物展开气泡聊天
  - 支持系统托盘、右键菜单、关闭到后台

远期：

- Phase 3 桌宠体验增强 + 养成体系
- Phase 4 QQ / IM / 移动端扩展

---

## 部署与安全注意事项

- 生产环境必须设置 `API_KEY`。
- 生产环境必须配置具体 `CORS_ORIGINS`。
- 对外部署应使用 HTTPS，由平台或反向代理终止 TLS。
- Render 免费实例的本地 SQLite 数据可能不持久，正式使用应考虑持久磁盘或迁移数据库。
- 生产环境建议 `LOG_LEVEL=WARNING`，避免记录过多用户内容。
- SQLite 文件在本地启动时会尝试设置为仅所有者可读写。