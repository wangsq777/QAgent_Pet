# QAgent Pet bug / 安全 / 优化追踪

> 最近核验：2026-07-07  
> 目标：只保留仍需处理的 Open / Partial 项；已修复问题压缩到“已修复归档”，避免旧审计描述误导后续开发。

---

## 当前仍需处理的问题

### P0 / P1：安全与数据隔离

#### C-1：认证与用户归属链路仍需收口

**状态：** Partial

**现状：**
- 已有 `AuthMiddleware`，支持 `API_KEY` 与 `X-User-Id`。
- `X-User-Id` 已做格式校验。
- 多数 session、learning、visits 路由已按 `request.state.user_id` 做归属校验。
- 但 `API_KEY` 为空时仍进入开发模式并跳过认证。
- ~~`custom_pets` 的部分详情/更新路径仍存在仅按 `pet_id` 查询的情况，需要统一补齐 `user_id` 条件。~~ **已修复（2026-07-07）：** `custom_pets` 的 GET/PUT 详情、`chat.py` 的 `get_catchphrase_async` / `get_custom_pet_info`、`sessions.py` 创建会话时的自定义宠物查询均已补齐 `user_id` 归属条件；`POST /api/sessions` 改用 `request.state.user_id`，请求体 `user_id` 不再可信（仅向后兼容保留字段）。

**建议：**
1. 生产环境强制配置 `API_KEY`，避免误以开发模式上线。
2. ~~所有自定义宠物详情、更新、内部查询函数统一使用 `pet_id + user_id`。~~ 已完成。
3. 保留预置宠物与自定义宠物的访问边界说明。

---

#### H-3 / M-5：LLM 工具调用仍依赖文本标记解析

**状态：** Partial

**现状：**
- 用户输入、MoodAgent、串门 topic / interjection、学习仓库内容已加入不同程度的 Prompt 注入隔离。
- `ToolExecutor` 已有工具白名单和参数校验。
- 但工具调用仍通过 LLM 文本输出中的标记/正则解析触发，尚未迁移到平台级 function calling / tool use。

**建议：**
1. 短期继续强化工具参数 schema 校验。
2. 中期将天气、日程等工具迁移为结构化 tool calling。
3. 所有新增工具默认按“不信任 LLM 文本参数”处理。

---

#### L-2：HTTPS 依赖部署环境

**状态：** Open / Deploy-dependent

**现状：**
- 本地 `uvicorn` 仍是 HTTP。
- 如果通过 Render / 反向代理访问，可由平台或 nginx / Caddy 终止 TLS。
- 仓库本身不强制 HTTPS。

**建议：**
- README / 部署说明中明确生产必须走 HTTPS。
- 若后续提供独立桌面客户端，桌面端连接本地后端可继续使用 localhost HTTP，但远程 API 必须 HTTPS。

---

### P1 / P2：性能与稳定性

#### M-2 / OPT-H-3：缺少全局 LLM 并发上限

**状态：** Partial

**现状：**
- chat、sessions、custom_pets、visits、learning 等关键端点已加 `slowapi` 限流。
- UserProfileAgent 已迁移到后台任务，MoodAgent 也在后台触发。
- 但外部 LLM 调用还没有全局 `asyncio.Semaphore` 并发上限。

**建议：**
1. 在 `llm_service` 增加全局并发信号量，例如 3-5。
2. 对非关键后台任务设置更短超时和失败降级。
3. 区分主回复、学习讲解、串门、后台画像等不同 caller 的限流和超时。

---

#### OPT-H-2：SQLite 向量检索仍是候选集内 Python 计算

**状态：** Partial

**现状：**
- 已新增 `(session_id, source_type)` 索引。
- 检索已限制最近 500 条候选，避免全表扫描。
- 但余弦相似度仍在 Python 中逐条计算。

**建议：**
- 短期保持 500 条候选限制。
- 长期如记忆规模明显增长，再评估 `sqlite-vec`、ChromaDB 或其他轻量向量检索方案。

---

#### OPT-M-1：SQLite 连接管理仍较轻量

**状态：** Partial

**现状：**
- 已启用 WAL 与 `synchronous=NORMAL`。
- 但 `get_db()` 仍是按需新建连接。

**建议：**
- 当前本地 / MVP 阶段可接受。
- 后续桌宠长期运行时，观察写锁和连接开销，再决定是否引入连接管理或迁移数据库。

---

#### VIS-4 / VIS-5：串门消息数与 active visit 并发边界仍可继续加固

**状态：** Partial

**现状：**
- visits 端点已加限流。
- guest 宠物归属、Prompt 注入、None persona、N+1 等主要问题已修复。
- 服务层已有消息数上限检查。
- 但消息数检查与最终 INSERT 之间仍有并发窗口，active visit 创建也可进一步使用显式 `BEGIN IMMEDIATE` 加强。

**建议：**
1. `generate_visit_turn()` 内把 COUNT 与 INSERT 放到同一个 `BEGIN IMMEDIATE` 写事务中。
2. 创建 visit 时也使用显式写事务，避免并发创建多个 active visit。
3. 如需要强约束，可增加数据库层唯一约束或状态表。

---

#### EMO-M-3：用户画像 merge 仍可进一步原子化

**状态：** Partial

**现状：**
- `merge_user_profile` 已有字段白名单、字段名正则和长度截断。
- 但读-改-写仍未显式使用 `BEGIN IMMEDIATE`。

**建议：**
- 将 `SELECT -> UPDATE/INSERT` 包入显式事务，避免 MoodAgent 与 UserProfileAgent 并发覆盖。

---

#### LEARN-L-3：学习奖励亲密度可能更新到同宠物的非预期 session

**状态：** Open

**现状：**
- 学习奖励发放已用事务避免重复领取。
- `_add_pet_intimacy` 仍通过用户 + 宠物定位 session，若同一用户同一宠物存在多个会话，可能更新到非预期会话。

**建议：**
- 学习会话创建时记录明确绑定的 `pet_session_id`。
- 奖励发放时按该 session 精确更新亲密度。

---

### P2 / P3：产品、部署与文档

#### OPT-M-4：日常分享逻辑仍可服务化

**状态：** Open

**现状：**
- 日常分享相关逻辑在 chat / sessions 路径中仍有重复。

**建议：**
- 提取 `proactive_service.py`，统一日常分享、主动关怀、提醒气泡的规则和文案生成。

---

#### OPT-L-1：自动化测试覆盖不足

**状态：** Open

**现状：**
- 当前测试仍偏脚本化。
- learning 有归属校验测试，但核心聊天、记忆、情绪解析、串门等缺少系统化 pytest 覆盖。

**建议：**
1. 引入 pytest / pytest-asyncio。
2. 对 `parse_emotional_reply`、亲密度计算、session 归属、learning 归属、visits 边界做稳定单测。
3. LLM 调用使用 mock，避免真实消耗。

---

#### OPT-L-2：Render 免费版 SQLite 数据持久化风险

**状态：** Open

**现状：**
- 本地 SQLite 适合 MVP。
- Render 免费 Web Service 文件系统可能不持久，重启或重新部署可能丢数据。

**建议：**
- Demo 前备份 `qagent_pet.db`。
- 正式使用考虑 Render Persistent Disk、PostgreSQL 或桌宠本地 `%APPDATA%/QAgentPet/` 数据目录。

---

#### OPT-L-4：前端当前会话依赖 localStorage，多标签页可能串线

**状态：** Open

**现状：**
- `frontend/js/app.js` 仍从 `localStorage.qagent_session_id` 读取当前会话。
- 多标签页同时打开不同宠物时，后打开页面可能覆盖 session。

**建议：**
1. 首页跳转聊天页时携带 `chat.html?session_id=xxx`。
2. 聊天页优先读取 URL 参数，localStorage 只作为最近使用记录。
3. 自定义宠物、学习页也同步采用明确 URL 参数。

---

## 已修复归档

### 主安全 / 配置

- 已修复：`X-User-Id` 前端适配与后端身份读取。
- 已修复：`X-User-Id` 格式校验。
- 已修复：API Key 比较改用 `secrets.compare_digest()`。
- 已修复：LLM / Embedding API Key 不再长期保存在服务实例属性中。
- 已修复：CORS 默认值改为本地域名配置，并在检测到 `*` 时输出警告。
- 已修复：请求体大小限制（1MB）。
- 已修复：SQLite 文件权限尝试设置为 `0o600`。
- 已修复：关键端点接入 `slowapi` 限流。

### 2026-07-07 安全加固（本轮）

- 已修复：`POST /api/sessions` 身份伪造——`create_session` 改用 `request.state.user_id`（`X-User-Id` 头经中间件校验），请求体 `user_id` 字段降级为可选并忽略，前端既有调用不受影响。
- 已修复：`custom_pets` GET/PUT 详情越权——`get_custom_pet` / `update_custom_pet` 的 SELECT 与 UPDATE 均补齐 `pet_id + user_id` 条件。
- 已修复：`chat.py` `get_catchphrase_async` / `get_custom_pet_info` 裸按 `pet_id` 读取——新增 `user_id` 参数并在 WHERE 中校验，`chat` 与 `sessions` 内所有调用点已传入 `request.state.user_id` / `session_dict["user_id"]`。
- 已修复：`sessions.py` 创建会话时对自定义宠物的二次查询（`SELECT pet_type, personality_tags, catchphrase FROM custom_pets WHERE pet_id = ?`）补齐 `user_id`。
- 已修复：Electron `desktop/main.js` `spawnBackend` 去除非必要 `shell: true`——非 Windows 一律 `shell:false`，Windows 仅因 `python` 可能是 `.cmd` 垫片而保留 `shell` 并加 `windowsHide` / `windowsVerbatimArguments`，参数固定无注入面。
- 部分修复：`ip_location.py` 明文 HTTP 与盲目信任 `X-Forwarded-For`——IP 查询优先 HTTPS，免费版 403 时回退 HTTP 并警告；`get_client_ip` 引入 `TRUSTED_PROXIES` 配置，仅在直连来源为可信代理时才采纳转发头，未配置时仅对回环地址退化为旧行为并警告。
- 已修复：`llm_service._clean_response` 的 thought/reasoning 正则可能误删合法 JSON——改为优先 `json.loads` 解析删除字段后重序列化，解析失败再退回保守正则兜底。

### LLM / 聊天稳定性

- 已修复：slowapi 参数名冲突导致聊天 500。
- 已修复：MiniMax Anthropic 兼容端点协议适配。
- 已修复：MiniMax thinking/text 多块响应解析。
- 已修复：MiniMax thinking 耗尽 token budget 导致无 text 块。
- 已修复：`main_chat` / `tool_feedback` 提升 `max_tokens`。
- 已修复：MiniMax-M2 系列追加 `chat_template_kwargs.enable_thinking=False` 压低 thinking 块。
- 已修复：messages 表 INSERT 占位符缺失。
- 已修复：`parse_emotional_reply` 对 None、空字符串、旧两字段格式、异常 JSON 做兜底。

### 情绪架构

- 已修复：主 LLM 情绪输出从 `reply/emotion` 升级为 `reply/emotion/need/intensity/risk_level`。
- 已修复：高风险 `risk_level=high` 安全回应兜底。
- 已修复：MoodAgent 首条消息误触发空历史分析。
- 已修复：MoodAgent 用户消息二阶 Prompt 注入过滤。
- 已修复：MoodAgent `should_trigger` 改为同步函数。
- 已修复：`_clean_response` 仅清理顶层 thought / reasoning，避免误删普通文本。
- 已修复：工具调用路径情绪字段协调覆盖。
- 已修复：用户画像字段白名单、字段名格式校验和字段长度截断。
- 已修复：日常分享概率改为 `random.random() < 0.33`。
- 已修复：session_id 格式校验相关路径补强。

### 自定义宠物

- 已修复：自定义宠物持久化存储。
- 已修复：自定义宠物删除及关联数据清理。
- 已修复：自定义宠物开场白 LLM 生成。
- 已修复：自定义宠物字段进入 prompt 前的注入过滤。
- 已修复：自定义宠物头像显示和 pet_type 写入问题。

### 串门 visits

- 已修复：VIS-1 guest_pet_id 归属验证缺失。
- 已修复：VIS-2 topic 和 user_interjection Prompt 注入过滤与长度限制。
- 已修复：VIS-3 visits 端点缺少限流。
- 已修复：VIS-6 end_visit 写入 guest 记忆前缺少归属验证。
- 已修复：VIS-7 next_turn / list_visits 对 None persona 无保护。
- 已修复：VIS-8 list_visits N+1 查询。
- 部分修复：VIS-4 / VIS-5 消息数和 active visit 并发边界，仍建议显式事务继续加固。

### 陪你学 learning

- 已修复：LEARN-H-1 GitHub 请求跟随重定向导致 SSRF 绕过。
- 已修复：LEARN-H-2 亲密度奖励竞态条件。
- 已修复：LEARN-M-1 仓库 README / 源码内容 Prompt 注入隔离。
- 已修复：LEARN-M-2 大纲字段类型校验不足。
- 已修复：LEARN-L-1 GitHub URL 编码处理。
- 已修复：LEARN-L-2 teacher_content 落库前长度截断。
- Won't Fix：LEARN-M-3 complete 端点 URL 前缀冲突，经核对不是 FastAPI 真实匹配冲突，改名风险大于收益。

### 前端 / 产品化

- 已修复：Web 主界面软件化 MVP。
- 已修复：宠物状态 API 与轻养成数据。
- 已修复：桌宠预览页和设置页。
- 已修复：首页、自定义宠物页、陪学页接入共享 App Shell。

---

## 当前修复优先级建议

| 优先级 | 项目 | 目标 |
|--------|------|------|
| ~~P0~~ | ~~C-1 自定义宠物详情/更新归属收口~~ | 已修复（2026-07-07），仅剩 API_KEY 开发模式未强制 |
| P1 | C-1 剩余项：生产强制 API_KEY + 可信代理配置 | 关闭开发模式与 X-Forwarded-For 伪造面 |
| P1 | 全局 LLM 并发信号量 | 防止高并发耗尽外部 API 与本地资源 |
| P1 | VIS-4 / VIS-5 显式事务加固 | 消除串门并发边界问题 |
| P1 | EMO-M-3 用户画像 merge 显式事务 | 避免后台画像并发覆盖 |
| P2 | LEARN-L-3 学习奖励绑定明确 pet_session_id | 避免同宠物多会话亲密度更新偏移 |
| P2 | OPT-L-4 URL session_id | 支持多标签页不同宠物并行 |
| P3 | 自动化测试体系 | 降低后续桌宠阶段回归风险 |
| P3 | SQLite 数据目录 / 持久化 | 为桌宠长期运行和备份恢复做准备 |