# QAgent Pet - Code Wiki 文档

## 1. 项目概述

QAgent Pet 是一个 **QQ智能宠物伴侣 Agent** 应用，提供拟人化的虚拟宠物互动体验。用户可以选择三种不同性格的宠物（热情小狗 Hot Dog、高冷猫咪 Cold Cat、胆小鼠鼠）进行聊天互动，系统具备情绪感知、日程管理、记忆存储等智能功能。

### 1.1 项目定位

| 属性 | 说明 |
|------|------|
| **项目名称** | QAgent Pet |
| **技术栈** | FastAPI + SQLite + MiniMax LLM + 原生前端 |
| **核心能力** | 拟人化对话、情绪感知、记忆系统、日程管理、工具调用 |
| **目标用户** | 寻求情感陪伴的用户 |

### 1.2 核心特性

- 🐕 **多宠物选择**：支持 Hot Dog（热情小狗）、Cold Cat（高冷猫咪）、Mouse（胆小鼠鼠）三种宠物
- 💬 **智能对话**：基于 MiniMax LLM 实现拟人化对话
- ❤️ **情绪感知**：自动识别用户情绪并做出相应响应
- 🧠 **记忆系统**：短期记忆 + 长期记忆压缩机制
- 📅 **日程管理**：自动识别并提醒用户日程安排
- 🌤️ **天气查询**：集成 Open-Meteo 提供天气查询能力
- 📊 **用户画像**：自动从对话中提取用户信息

---

## 2. 项目架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端层 (frontend/)                       │
│  index.html (宠物选择)    chat.html (聊天界面)    css/  js/     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP REST API
┌──────────────────────────▼──────────────────────────────────────┐
│                        API层 (routers/)                         │
│    sessions.py (会话管理)           chat.py (聊天逻辑)           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 服务调用
┌──────────────────────────▼──────────────────────────────────────┐
│                        服务层 (services/)                       │
│  llm_service.py    memory_service.py    weather_service.py      │
│  tool_executor.py  user_profile_agent.py ip_location.py         │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 数据访问
┌──────────────────────────▼──────────────────────────────────────┐
│                     数据层 (database/models/schemas)            │
│   database.py (连接池)    models.py (数据模型)    schemas.py    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责表

| 模块 | 路径 | 职责 |
|------|------|------|
| **入口模块** | `main.py` | FastAPI 应用初始化、路由注册、静态文件服务 |
| **配置管理** | `backend/config.py` | 环境变量读取、全局配置对象 |
| **数据库** | `backend/database.py` | SQLite 连接、表结构定义、连接池管理 |
| **数据模型** | `backend/models.py` | 业务实体的数据类定义 |
| **API Schema** | `backend/schemas.py` | 请求/响应数据结构定义 |
| **会话路由** | `backend/routers/sessions.py` | 会话创建、日常分享、时间模拟、记忆面板 |
| **聊天路由** | `backend/routers/chat.py` | 消息发送、工具调用、情绪分析、用户画像更新 |
| **LLM服务** | `backend/services/llm_service.py` | MiniMax API 封装、消息生成、情绪提取 |
| **记忆服务** | `backend/services/memory_service.py` | 消息存储、长期记忆压缩、用户画像管理 |
| **天气服务** | `backend/services/weather_service.py` | Open-Meteo API 封装、天气查询工具 |
| **工具执行器** | `backend/services/tool_executor.py` | 工具注册、调用解析、结果处理 |
| **用户画像Agent** | `backend/services/user_profile_agent.py` | 从对话中提取用户信息 |
| **IP定位服务** | `backend/services/ip_location.py` | 通过IP获取用户地理位置 |
| **提示词配置** | `backend/prompts/` | 各宠物角色的系统提示词定义 |

---

## 3. 目录结构

```
QAgent_Pet/
├── main.py                    # 项目入口
├── requirements.txt           # 依赖声明
├── .env.example              # 环境变量模板
├── render.yaml               # Render 部署配置
├── backend/                  # 后端核心模块
│   ├── __init__.py
│   ├── config.py             # 配置管理
│   ├── database.py           # 数据库连接
│   ├── models.py             # 数据模型
│   ├── schemas.py            # API Schema
│   ├── routers/              # API路由
│   │   ├── __init__.py
│   │   ├── sessions.py       # 会话管理接口
│   │   └── chat.py           # 聊天接口
│   ├── services/             # 核心服务
│   │   ├── __init__.py
│   │   ├── llm_service.py    # LLM调用服务
│   │   ├── memory_service.py # 记忆管理服务
│   │   ├── weather_service.py # 天气服务
│   │   ├── tool_executor.py  # 工具执行器
│   │   ├── user_profile_agent.py # 用户画像Agent
│   │   └── ip_location.py    # IP定位服务
│   └── prompts/              # 宠物提示词
│       ├── __init__.py
│       ├── hot_dog.py        # 热情小狗
│       ├── cold_cat.py       # 高冷猫咪
│       └── mouse.py          # 胆小鼠鼠
├── frontend/                  # 前端代码
│   ├── index.html            # 宠物选择页
│   ├── chat.html             # 聊天界面
│   ├── css/                  # 样式文件
│   ├── js/                   # JavaScript
│   └── images/               # 宠物图片
└── docs/                     # 文档
    └── QAgent_Pet_产品方案.md
```

---

## 4. 关键类与函数说明

### 4.1 配置模块

#### Settings 类 (`backend/config.py`)

```python
class Settings(BaseSettings):
    LLM_API_KEY: str = ""          # MiniMax API Key
    LLM_BASE_URL: str = "https://api.minimax.chat/v1"
    LLM_MODEL: str = "MiniMax-M2.5"
    WEATHER_API_KEY: str = ""      # 可选，备用天气API
    DATABASE_URL: str = "sqlite+aiosqlite:///./qagent_pet.db"
    PORT: int = 10000
```

**说明**：使用 `pydantic-settings` 从 `.env` 文件加载配置，支持类型自动转换和默认值。

---

### 4.2 数据库模块

#### 数据库表结构 (`backend/database.py`)

| 表名 | 用途 | 核心字段 |
|------|------|----------|
| `users` | 用户信息 | user_id, nickname, created_at |
| `pet_sessions` | 宠物会话 | session_id, user_id, pet_type, intimacy, pet_status |
| `messages` | 消息记录 | message_id, session_id, role, content, emotion_tag |
| `long_term_memories` | 长期记忆 | memory_id, session_id, summary |
| `schedules` | 日程安排 | schedule_id, session_id, content, scheduled_time |
| `user_profiles` | 用户画像 | profile_id, user_id, region, identity, interests |

#### 关键函数

| 函数 | 说明 | 参数 | 返回值 |
|------|------|------|--------|
| `init_database()` | 初始化数据库表 | 无 | None |
| `get_db()` | 获取数据库连接（上下文管理器） | 无 | aiosqlite.Connection |

---

### 4.3 数据模型 (`backend/models.py`)

| 模型类 | 说明 | 关键字段 |
|--------|------|----------|
| `User` | 用户实体 | user_id, nickname |
| `PetSession` | 宠物会话 | session_id, user_id, pet_type, intimacy, pet_status |
| `Message` | 消息实体 | message_id, session_id, role, content, emotion_tag |
| `LongTermMemory` | 长期记忆 | memory_id, session_id, summary |
| `Schedule` | 日程实体 | schedule_id, session_id, content, scheduled_time |
| `UserProfile` | 用户画像 | profile_id, user_id, region, identity, interests |

---

### 4.4 API Schema (`backend/schemas.py`)

| Schema | 用途 | 关键字段 |
|--------|------|----------|
| `SessionCreateRequest` | 创建会话请求 | user_id, pet_type, nickname |
| `SessionResponse` | 会话响应 | session_id, pet_type, welcome_message, intimacy |
| `ChatRequest` | 聊天请求 | content |
| `ChatResponse` | 聊天响应 | reply, emotion_tag, intimacy, schedule_extracted |
| `MemoryPanelResponse` | 记忆面板响应 | intimacy, intimacy_level, long_term_memories, user_profile |
| `UserProfileUpdateRequest` | 用户画像更新请求 | region, identity, interests |

---

### 4.5 服务层核心类

#### LLMService (`backend/services/llm_service.py`)

**职责**：封装 MiniMax LLM API 调用，提供消息生成、情绪提取、记忆压缩等能力。

| 方法 | 说明 | 参数 | 返回值 |
|------|------|------|--------|
| `chat()` | 通用聊天接口 | messages, temperature, max_tokens | Optional[str] |
| `generate_welcome_message()` | 生成欢迎消息 | pet_type, pet_name, pet_personality | str |
| `generate_proactive_message()` | 生成主动关怀消息 | pet_type, pet_name, reason | Optional[str] |
| `extract_emotion()` | 提取用户情绪 | user_message, pet_type | str |
| `extract_user_profile()` | 提取用户画像信息 | user_message, conversation_history | Optional[Dict] |
| `compress_memory()` | 压缩对话为记忆摘要 | messages, pet_name | str |

#### MemoryService (`backend/services/memory_service.py`)

**职责**：管理消息存储、长期记忆、用户画像数据。

| 方法 | 说明 | 参数 | 返回值 |
|------|------|------|--------|
| `get_short_term_messages()` | 获取短期消息 | session_id, limit | List[MessageResponse] |
| `save_message()` | 保存消息 | session_id, role, content, emotion_tag | str (message_id) |
| `compress_to_long_term()` | 压缩消息到长期记忆 | session_id, messages, pet_name | Optional[str] |
| `get_long_term_memories()` | 获取长期记忆列表 | session_id | List[Dict] |
| `update_user_profile()` | 更新用户画像 | user_id, profile_data | None |
| `merge_user_profile()` | 合并用户画像（增量更新） | user_id, profile_data | None |

#### ToolExecutor (`backend/services/tool_executor.py`)

**职责**：工具注册、调用解析、执行管理（支持 ReAct 模式）。

| 方法 | 说明 | 参数 | 返回值 |
|------|------|------|--------|
| `register()` | 注册工具函数 | name, func | None |
| `execute()` | 执行工具调用 | tool_name, args | ToolResult |
| `parse_tool_calls()` | 解析LLM输出中的工具调用 | text | List[Dict] |
| `remove_tool_calls()` | 移除回复中的工具调用标记 | text | str |

#### WeatherService (`backend/services/weather_service.py`)

**职责**：封装 Open-Meteo API，提供天气查询能力。

| 方法 | 说明 | 参数 | 返回值 |
|------|------|------|--------|
| `get_weather()` | 获取天气信息 | location (城市名) | Optional[Dict] |
| `query_weather_tool()` | 工具调用接口 | location | str (格式化天气描述) |

#### UserProfileAgent (`backend/services/user_profile_agent.py`)

**职责**：从对话历史中自动提取用户画像信息（地区、身份、兴趣等）。

| 方法 | 说明 | 参数 | 返回值 |
|------|------|------|--------|
| `analyze_and_extract()` | 分析对话提取画像 | conversation_history, existing_profile | Optional[Dict] |

---

### 4.6 路由模块

#### Sessions Router (`backend/routers/sessions.py`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sessions` | POST | 创建/获取会话 |
| `/api/sessions/{session_id}` | GET | 获取会话详情 |
| `/api/sessions/{session_id}/share-daily` | POST | 分享日常 |
| `/api/sessions/{session_id}/share-daily-random` | POST | 概率触发分享日常 |
| `/api/sessions/{session_id}/simulate-time` | POST | 模拟时间流逝 |
| `/api/sessions/{session_id}/memory` | GET | 获取记忆面板 |
| `/api/sessions/{session_id}/profile` | PUT | 更新用户画像 |

#### Chat Router (`backend/routers/chat.py`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sessions/{session_id}/chat` | POST | 发送消息（核心聊天接口） |
| `/api/sessions/{session_id}/messages` | GET | 获取消息列表 |

---

### 4.7 宠物角色配置 (`backend/prompts/`)

三种宠物角色的核心属性：

| 属性 | Hot Dog | Cold Cat | Mouse |
|------|---------|----------|-------|
| **名称** | Hot Dog | Cold Cat | 鼠鼠 |
| **性格** | 超级热情、活泼、真诚 | 外表高冷、内心在意 | 老实憨厚、胆子小 |
| **口头禅** | 汪！主人！ | 哼。......才不是关心你。 | 鼠鼠我啊...... |
| **主动关怀时机** | 1天不互动 | 3天不互动（50%概率） | 2天不互动 |
| **躲藏机制** | 无 | 无 | 3天不互动后突然出现会躲藏 |

---

## 5. 核心业务流程

### 5.1 会话创建流程

```
用户选择宠物 → 创建/复用会话 → 生成欢迎消息 → 返回会话信息
     ↓
检查用户是否存在 → 不存在则创建用户和画像 → 创建宠物会话
```

### 5.2 聊天流程（ReAct 模式）

```
用户发送消息 → 构建上下文（记忆+画像+技能） → 调用LLM生成回复
     ↓
解析工具调用 → 执行工具（如天气查询） → 工具结果反馈给LLM
     ↓
生成最终回复 → 提取日程 → 更新用户画像 → 压缩长期记忆 → 返回响应
```

### 5.3 记忆压缩机制

```
消息数 > 20 且为20的倍数时触发：
  获取最近40条消息 → 调用LLM压缩为200字摘要 → 存储到长期记忆表
```

### 5.4 情绪响应机制

| 用户情绪 | Hot Dog 响应 | Cold Cat 响应 | Mouse 响应 |
|----------|-------------|--------------|-----------|
| happy | 欢快附和，求摸摸 | 平淡简洁，淡淡附和 | 为主人高兴 |
| sad | 软糯安慰，默默陪伴 | 别扭关心，简短包容 | 小声询问，安慰 |
| anxious | 温柔安抚，别着急 | 极简缓和，漫不经心 | 担心陪伴 |
| tired | 软软提醒休息 | 简短暗示休息 | 小心劝休息 |
| neutral | 分享趣事，热情互动 | 高冷常态，偶尔幽默 | 正常互动 |

---

## 6. API 接口速查

### 6.1 会话管理

| 接口 | 方法 | 请求体 | 响应体 |
|------|------|--------|--------|
| `/api/sessions` | POST | `{"user_id": "xxx", "pet_type": "hot_dog"}` | `SessionResponse` |
| `/api/sessions/{id}` | GET | 无 | 会话详情 |
| `/api/sessions/{id}/memory` | GET | 无 | `MemoryPanelResponse` |
| `/api/sessions/{id}/profile` | PUT | `{"region": "北京", "identity": "..."}` | 更新后的画像 |

### 6.2 聊天接口

| 接口 | 方法 | 请求体 | 响应体 |
|------|------|--------|--------|
| `/api/sessions/{id}/chat` | POST | `{"content": "你好"}` | `ChatResponse` |
| `/api/sessions/{id}/messages` | GET | 无 | `MessageListResponse` |

### 6.3 时间模拟

| 接口 | 方法 | 请求体 | 说明 |
|------|------|--------|------|
| `/api/sessions/{id}/simulate-time` | POST | `{"mode": "next_day"}` | 模拟隔天 |
| `/api/sessions/{id}/simulate-time` | POST | `{"mode": "schedule_trigger"}` | 触发日程提醒 |

---

## 7. 项目运行

### 7.1 环境要求

- Python 3.10+
- pip 包管理工具

### 7.2 安装依赖

```bash
pip install -r requirements.txt
```

### 7.3 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```env
# MiniMax API Key（必填）
LLM_API_KEY=your_minimax_api_key_here
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_MODEL=MiniMax-M2.5

# 服务配置
DATABASE_URL=sqlite+aiosqlite:///./qagent_pet.db
PORT=10000
```

### 7.4 启动服务

```bash
# 开发模式
python main.py

# 或使用 uvicorn 直接启动
uvicorn main:app --host 0.0.0.0 --port 10000
```

### 7.5 访问应用

- 后端 API：`http://localhost:10000`
- 前端页面：`http://localhost:10000/frontend/index.html`

---

## 8. 数据流向图

```
用户前端                      后端服务                      外部服务
   │                             │                             │
   │──创建会话──────────────────▶│                             │
   │                             │──检查用户─────────────────▶│ SQLite
   │                             │──创建会话─────────────────▶│
   │◀──返回会话信息──────────────│                             │
   │                             │                             │
   │──发送消息──────────────────▶│                             │
   │                             │──构建上下文────────────────▶│ MemoryService
   │                             │──调用LLM──────────────────▶│ MiniMax API
   │                             │                             │
   │                             │──[需要工具？]──────────────▶│
   │                             │     └──天气查询──────────▶│ Open-Meteo
   │                             │                             │
   │                             │──提取情绪──────────────────▶│ LLM
   │                             │──提取画像──────────────────▶│ UserProfileAgent
   │                             │──压缩记忆──────────────────▶│ LLM
   │                             │                             │
   │◀──返回回复──────────────────│                             │
   │                             │                             │
```

---

## 9. 关键设计决策

### 9.1 记忆系统设计

- **短期记忆**：最近40条消息，用于对话上下文
- **长期记忆**：每20轮对话压缩一次，存储为摘要
- **用户画像**：独立存储，从对话中自动提取更新

### 9.2 工具调用机制（ReAct）

采用 ReAct 模式实现工具调用：
1. LLM 在回复中嵌入 `[TOOL_CALL]` 标记
2. 后端解析并执行工具
3. 将工具结果反馈给 LLM 生成最终回复

### 9.3 宠物差异化设计

通过不同的系统提示词实现宠物性格差异化：
- Hot Dog：热情活泼，频繁主动关怀
- Cold Cat：高冷傲娇，30%概率懒说话
- Mouse：胆小害羞，可能躲藏

### 9.4 情绪感知与亲密度

- 情绪标签：happy、sad、anxious、tired、neutral
- 亲密度增长：sad情绪+3，其他+1，上限100
- 亲密度等级：陌生(0-20)→熟悉(21-50)→亲密(51-80)→挚友(81-100)

---

## 10. 部署说明

### 10.1 Render 部署

项目已配置 `render.yaml`，可直接部署到 Render：

```yaml
services:
  - type: web
    name: qagent-pet
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: LLM_API_KEY
        value: your_minimax_api_key
```

### 10.2 环境变量清单

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `LLM_API_KEY` | 是 | - | MiniMax API Key |
| `LLM_BASE_URL` | 否 | `https://api.minimax.chat/v1` | LLM API地址 |
| `LLM_MODEL` | 否 | `MiniMax-M2.5` | 使用的模型 |
| `DATABASE_URL` | 否 | `sqlite+aiosqlite:///./qagent_pet.db` | 数据库连接 |
| `PORT` | 否 | `10000` | 服务端口 |

---

## 11. 扩展指南

### 11.1 添加新宠物类型

1. 在 `backend/prompts/` 新建提示词文件
2. 在 `backend/routers/sessions.py` 和 `chat.py` 中添加宠物类型判断
3. 在前端 `frontend/js/app.js` 中添加宠物配置
4. 添加宠物图片到 `frontend/images/`

### 11.2 添加新工具

1. 创建服务类实现工具方法
2. 在 `backend/routers/chat.py` 中注册工具
3. 更新提示词中的工具说明

---

## 12. 故障排查

### 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| LLM 无响应 | API Key 未配置或无效 | 检查 `.env` 中的 `LLM_API_KEY` |
| 天气查询失败 | 城市名无法识别 | 使用标准城市名，如"北京"、"上海" |
| 数据库连接失败 | 路径权限问题 | 确保应用有写入权限 |
| 前端无法连接 | CORS 问题 | 检查 `main.py` 中的 CORS 配置 |

### 日志查看

关键日志输出：
- `[LLM][caller]` - LLM 调用日志
- `[Tool]` - 工具调用日志
- `[MemoryService]` - 记忆操作日志
- `[UserProfileAgent]` - 用户画像提取日志