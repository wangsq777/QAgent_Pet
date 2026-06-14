# QAgent Pet 更新记录

---

## 2026-06-14（第三次）

**修复：MiniMax 思考模型响应解析失败导致所有 LLM 调用返回 None**

**问题现象：** 更新 API 地址后，`main_chat` 偶尔正常，但 `[chat]`（情绪提取）、`[topic_detect]`、`[user_profile_agent]` 等调用全部报错 `KeyError: 'text'` 或 `No text block found`，宠物回复均为 fallback 默认文本。

**根本原因：**
1. **响应解析错误**：`MiniMax-M2.7` 是 Extended Thinking（扩展思考）模型，返回的 `content` 数组中第一个元素是 `{"type": "thinking", ...}` 思考块，实际回复文本在后面的 `{"type": "text", "text": "..."}` 块。原代码直接取 `data["content"][0]["text"]`，永远拿到的是思考块，导致 `KeyError: 'text'`。
2. **token 预算不足**：情绪提取（`max_tokens=20`）、话题检测（`max_tokens=10`）等调用的 token 上限极小，思考模型把所有 token 预算都用在 thinking 上，没有剩余空间输出文本块，导致 content 里只有 thinking 块没有 text 块。

**修复方案：**
- `backend/services/llm_service.py`：响应解析改为遍历 `content` 列表寻找 `type == "text"` 的块，兼容思考模型多块响应；同时兼容 OpenAI 格式（`choices[0].message.content`）作为 fallback
- `backend/services/llm_service.py`：所有 `max_tokens` 偏小的调用统一提升至 1000~1500，为 thinking + 文本输出预留足够空间
- `backend/services/memory_service.py`：话题检测调用 `max_tokens` 从 10 提升至 1000

**改动文件：**
- `backend/services/llm_service.py`
- `backend/services/memory_service.py`

---

## 2026-06-14（第二次）

**修复：LLM 服务协议不匹配导致 404 错误**

**问题现象：** 聊天接口不再报 500，但 LLM 调用全部返回 404，宠物回复都是 fallback 默认文本。

**根本原因：** `.env` 中 `LLM_BASE_URL=https://api.minimaxi.com/anthropic` 是 MiniMax 的 **Anthropic 兼容端点**，但 `llm_service.py` 使用的是 **OpenAI 协议**：
- 端点：`/chat/completions`（OpenAI）→ 拼接后地址不存在
- 认证：`Authorization: Bearer`（OpenAI）→ Anthropic 端点要求 `x-api-key`
- 响应解析：`data["choices"][0]["message"]["content"]`（OpenAI）→ Anthropic 返回 `data["content"][0]["text"]`

**修复方案：** 将 `_call_llm` 方法改为 Anthropic Messages API 协议：
- 端点：`{base_url}/v1/messages`
- 认证头：`x-api-key` + `anthropic-version: 2023-06-01`
- system 消息从 messages 列表中分离为独立 `system` 字段
- 响应解析改为 `data["content"][0]["text"]`

**改动文件：**
- `backend/services/llm_service.py`：`_call_llm` 方法协议适配

---

## 2026-06-14

**修复：聊天接口 slowapi 参数名冲突导致 500 错误**

**问题现象：** 用户与宠物 Agent 对话时发送消息失败，后台报 500 Internal Server Error。

**根本原因：** `backend/routers/chat.py` 的 `chat` 函数中，`@limiter.limit("20/minute")` 装饰器（slowapi）会自动查找名为 `request` 的参数并期望其为 `starlette.requests.Request` 类型。但函数签名中 `request` 参数实际是 `ChatRequest`（Pydantic 模型），导致 slowapi 抛出异常：

```
Exception: parameter `request` must be an instance of starlette.requests.Request
```

**修复方案：** 将 `request: ChatRequest` 重命名为 `chat_req: ChatRequest`，并更新函数内所有引用（`request.content` → `chat_req.content`）。

**改动文件：**
- `backend/routers/chat.py`：参数重命名及相关引用更新

---

## 2026-06-13（第四次）

**文档重构：本地演示方案独立成文**

将原本嵌入在 `docs/plan.md` 中的”本地演示方案”章节提取为独立文档 `docs/demo.md`，保持 `plan.md` 仅包含需求记录。

**变更内容：**
- 新建 `docs/demo.md`：完整的本地演示指南
- 更新 `docs/plan.md`：移除演示方案章节，仅保留需求规划记录
- 演示方案内容完整保留：项目概述、演示目标、环境准备、启动步骤、6幕演示脚本、功能亮点、故障兜底、检查清单、快速重置方法

**文档结构：**
- `docs/plan.md` — 需求规划与技术实现记录
- `docs/demo.md` — 本地演示操作指南
- `docs/update.md` — 项目更新日志

---

## 2026-06-13（第三次）

**新增文档：本地演示方案**

在 `docs/plan.md` 中新增”本地演示方案”章节（`[2026-06-13] Plan for 本地演示方案`），不涉及任何业务代码修改。

**文档内容涵盖：**
- 演示目标：主动关怀、记忆延续、个性化角色三大核心价值
- 准备环境：Python 版本要求、API Key 配置、依赖安装步骤
- 启动步骤：`python main.py` 启动方式与成功标志
- 推荐演示脚本：6 幕演示顺序（宠物选择 → 情绪感知 → 日程记忆 → 主动关怀 → 记忆面板 → 自定义宠物）
- 重点功能亮点汇总表
- 故障兜底方案：9 类常见问题及处理方式
- 演示前检查清单：11 项检查项
- 快速重置演示环境方法（清空数据库）

---

## 2026-06-13（第二次）

**OPT-H-1: 前端适配用户身份隔离**

完成前端代码更新，使所有 API 请求携带 `X-User-Id` 请求头：

**前端改动：**
- `frontend/js/api.js`：新增 `getUserId()` 和 `buildHeaders()` 工具函数
- 所有 API 调用（createSession、chat、getMessages 等）统一使用 `buildHeaders()` 构建请求头
- 自动从 `localStorage.qagent_user_id` 读取用户 ID，未提供时 fallback 为 `"anonymous"`

**完整用户隔离链路：**
1. 用户首次访问 `index.html` 时生成唯一 `user_id` 并存入 `localStorage`
2. 前端每次请求自动携带 `X-User-Id` 请求头
3. 后端 `AuthMiddleware` 提取并存入 `request.state.user_id`
4. 所有路由通过 `request.state.user_id` 进行归属验证
5. 不同用户的 session/pet 完全隔离，互不可见

**验证结果：**
- ✅ 服务器启动正常，无报错
- ✅ CORS 允许 `X-User-Id` 请求头
- ✅ 403 Forbidden 错误已消除（需刷新浏览器清除旧 session）

---

## 2026-06-13

**OPT-H-1: 实现完整用户身份隔离（后端部分）**

根据 `docs/bug.md` 中 OPT-H-1 的建议，实现真正的多用户身份隔离机制：

**核心改动：**
- `backend/auth.py`：从 `X-User-Id` 请求头读取用户身份，存入 `request.state.user_id`
- `backend/routers/sessions.py`：所有路由从 `request.state.user_id` 读取用户身份，移除硬编码 `"default_user"`
- `backend/routers/chat.py`：聊天和消息路由改用 `http_request.state.user_id` 进行归属验证
- `backend/routers/custom_pets.py`：自定义宠物路由改用 `http_request.state.user_id`，删除接口移除 query 参数
- `main.py`：CORS 中间件添加 `X-User-Id` 到 `allow_headers`

**身份验证流程：**
1. 前端请求携带 `X-User-Id: <user_id>` 请求头
2. AuthMiddleware 提取并验证（API_KEY 存在时）
3. 存入 `request.state.user_id`
4. 所有路由通过 `request.state.user_id` 获取当前用户身份
5. Session/Pet 归属校验改为 `session.user_id == request.state.user_id`

**兼容性：**
- 未提供 `X-User-Id` 时 fallback 为 `"anonymous"`
- 现有前端需更新请求头，添加 `X-User-Id`
- 数据库 schema 无需变更，`user_id` 字段已支持任意字符串

---

## 2026-06-12（第二次）

根据 `docs/bug.md` 优化追踪文档，修复以下问题：

**安全修复：**
- **M-1**：`backend/services/ip_location.py` 剩余 `print()` 替换为 `logger.warning()`，引入 `logging_config.get_logger`。
- **H-3**：`backend/services/llm_service.py` 新增 `_sanitize_prompt_input()` 函数，在 `extract_emotion()` 和 `extract_schedule()` 入口处过滤用户输入的 XML 标签与指令分隔符；`backend/routers/chat.py` 同步将 `extract_emotion` 调用从 `request.content` 改为 `sanitized_content`。
- **H-2**：`backend/auth.py` API Key 比较由 `==` 改为 `secrets.compare_digest()`，防止时序攻击；`API_KEY` 为空时输出 WARNING 日志。
- **OPT-M-5**：`main.py` 启动时若 `CORS_ORIGINS` 包含 `*` 则输出 WARNING 日志，提醒生产环境配置具体域名。
- **OPT-M-6**：`backend/prompts/custom_pet.py` 的 `generate_custom_pet_system_prompt()` 入口处对 `pet_name` 和 `catchphrase` 调用 `_sanitize_user_input()`，补齐自定义宠物字段 Prompt 注入防护。

**数据库优化：**
- **OPT-M-3**：`backend/database.py` 迁移 `try-except` 改为仅忽略 `duplicate column name` 错误，其他异常记录日志并重新抛出。
- **OPT-M-1**：`backend/database.py` `init_database()` 启用 `PRAGMA journal_mode=WAL` 和 `PRAGMA synchronous=NORMAL`，提升并发写入稳定性。
- **OPT-H-2**：`backend/database.py` 新增 `(session_id, source_type)` 联合索引；`backend/services/embedding_service.py` 向量检索改为 `ORDER BY created_at DESC LIMIT 500`，避免全量扫描。

**性能/限流：**
- **M-2**：`backend/routers/chat.py` 引入 `slowapi.Limiter`，对 `POST /{session_id}/chat` 端点添加 `@limiter.limit("20/minute")` 装饰器，防止高频请求耗尽 API 配额。

---

## 2026-06-12

- 核验 `docs/bug.md` 中 2025-06-11 旧安全问题的当前修复状态。
- 删除已修复或已转移追踪的旧问题：M-4 中 `special_habits` 长度限制与入 prompt 前过滤已修复，`pet_name` / `catchphrase` 过滤缺口转至 OPT-M-6 继续追踪；L-3（请求体大小限制）已完整修复。
- 为仍未完全修复的问题补充 2026-06-12 核验说明，包括认证、CORS、Prompt 注入、日志、限流、输入验证、工具调用、SQLite 文件权限与 HTTPS 部署项。

---

