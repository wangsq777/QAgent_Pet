# QAgent Pet 更新记录

---

## 2026-07-01（功能：Phase 0 情感捕捉细化落地）

实现 `docs/plan.md` 中 `[2026-06-30] Plan for 情感捕捉细化` 与 `[2026-07-01] 产品转型阶段化落地` 的 Phase 0，将主 LLM 结构化输出从两字段升级为五字段，新增情感需求/强度/风险维度，并接入亲密度计算、安全回应与记忆压缩。

**1. 文档重构：**
- `docs/plan.md`：将已完成的 `[2026-06-17] 情绪感知两层架构重构` 详细计划替换为一行「需求：情绪感知两层架构重构已实现。」，删除其实现路径描述，保持 plan.md 只承载待实现需求。

**2. 主 LLM 结构化输出升级（`backend/routers/chat.py`）：**
- 新增 `parse_emotional_reply(raw)` 返回 `EmotionalReply` 对象，五字段 `reply/emotion/need/intensity/risk_level`；三层兜底（直接 JSON 解析 → 正则提取最外层 JSON → 纯文本原文）；兼容旧两字段格式（缺字段走安全默认 `need=unknown/intensity=1/risk_level=none`）；非法值降级（`emotion`→neutral、`need`→unknown、`intensity` 钳到 1-5、`risk_level`→none）。
- 保留 `parse_structured_reply()` 旧接口作为兼容垫片，内部委托 `parse_emotional_reply`。
- `full_prompt` 与工具路径 `second_prompt` 末尾均改为要求输出五字段 JSON，并强调这些字段是系统内部判断、不得在 `reply` 里告诉用户"你现在是某某情绪"。
- 工具路径 `execute_tools_and_build_final_prompt` 返回值从 `(str, dict, str)` 改为 `(str, dict, EmotionalReply)`；首轮与工具路径情感字段做协调覆盖（工具路径给出有意义字段才覆盖首轮）。

**3. 亲密度计算改造（`backend/routers/chat.py`）：**
- `calculate_intimacy_change(emotion, need, intensity)` 从只看 `emotion_tag` 升级为结合三维度：sad/anxious 基础分更高、陪伴/倾诉/认可/鼓励/安抚类需求加成、高强度情感加成，上限 3。

**4. 高风险安全回应策略（`backend/routers/chat.py`）：**
- 新增 `generate_safe_crisis_reply(pet_type, pet_name)`：`risk_level=high` 时在安全规则约束下重新生成回复，保持宠物人格但优先安全、不开玩笑、引导联系现实可信任的人/紧急求助、声明本产品非专业心理咨询；LLM 失败时返回固定安全模板。
- chat 主流程在解析出 `risk_level=high` 后调用该函数覆盖回复，并将 `need` 标记为 `crisis_support`。

**5. MoodAgent 结构化趋势升级（`backend/services/mood_agent.py`）：**
- `analyze_mood_tendency` 从输出 20 字简单倾向升级为结构化 JSON：`mood_tendency/dominant_emotion/dominant_need/suggested_support_style`。
- `mood_tendency` 仍写入 `user_profiles`（schema 唯一支持字段），其余字段记录到日志供后续主动关怀策略扩展。
- 解析失败时退回旧版纯文本兜底，异常仍不影响主响应路径。

**6. messages 表情感字段落库（`backend/database.py` + `backend/services/memory_service.py`）：**
- `messages` 表新增 `emotional_need TEXT`、`emotion_intensity INTEGER`、`risk_level TEXT` 三列，采用与 `user_profiles` 相同的 `ALTER TABLE` + 忽略 "duplicate column name" 的兼容迁移范式（幂等）。
- `memory_service.save_message` 签名扩展新增三参数，INSERT 同步落库；chat 主流程在保存 assistant 消息时传入本轮情感字段。

**7. 记忆压缩保留情感事件（`backend/services/llm_service.py`）：**
- `compress_memory` Prompt 增加要求：保留用户重要情绪事件、情感支持偏好、压力来源与有效安抚方式；情感类记忆 `importance` 适当提高，降低被时间衰减影响的速度。

**验证结果：**
- ✅ `python -m py_compile` 全量文件语法检查通过（chat/mood_agent/memory_service/llm_service/database）
- ✅ `import main` 导入无误
- ✅ `parse_emotional_reply` 单测覆盖：新格式完整提取、旧两字段兼容、JSON 前后带冗余文字正则提取、纯文本 fallback、非法 emotion/need/intensity/risk 降级、空/None 兜底
- ✅ `calculate_intimacy_change` 单测覆盖：sad+venting+4→3、neutral+unknown+1→1、happy+celebration+2→1、anxious+calming+5→3
- ✅ 数据库迁移幂等：临时库与真实库均成功新增三列，重复执行不报错
- ✅ 前端零改动（`ChatResponse` 不变，新字段仅内部落库不暴露给前端）

---

## 2026-07-01（文档：产品转型阶段化落地计划）

根据产品转型方向文档与当前需求计划，在 `docs/plan.md` 中新增 `[2026-07-01] Plan for 产品转型阶段化落地`。

本次仅更新规划文档，未修改业务代码。

**规划重点：**
- 将产品主线明确为「个人 AI 电子宠物伴侣」，现有 FastAPI 后端作为统一的 `QAgent Pet Core`
- 明确 Web 端继续作为完整功能中心，桌宠端作为下一阶段重点入口，QQ/IM 降级为远期可选扩展
- 梳理总体路线：Phase 0 情感捕捉细化 → Phase 1 产品定位调整与 Web 宠物化 → Phase 2 桌宠 MVP → Phase 3 桌宠体验增强与养成体系 → Phase 4 多端扩展
- 为每个阶段补充目标、交付物、涉及模块和验收标准
- 明确阶段依赖、优先级、关键风险与缓解措施
- 提出实施建议：先落地情感结构化，桌宠不重写后端，MVP 不过早引入 Live2D，数据迁移放到桌宠稳定后推进

---

## 2026-06-30（文档：产品转型方向）

根据当前产品方向讨论，新增 `docs/产品转型方向文档.md`，用于记录 QAgent Pet 从「QQ 内部聊天宠物」拓展为「个人 AI 电子宠物伴侣」的转型方向。

本次仅新增规划文档，未修改业务代码。

**文档重点：**
- 明确当前仅围绕 QQ Bot 推进会限制现有 Web 端能力展示，且与豆包等通用 AI 助手差异化不足
- 将产品主线调整为「个人 AI 电子宠物伴侣」，QQ / IM 接入降级为远期可选入口
- 保留现有 Web 端作为完整功能中心，承载宠物选择、自定义宠物、完整聊天、记忆面板、陪我学、串门和设置管理
- 新增桌宠端方向，定位为常驻桌面的轻量陪伴入口，负责透明置顶宠物、气泡聊天、主动提醒、动画状态和托盘菜单
- 梳理与通用 AI 助手的差异化：从工具型 AI 转向关系型 AI 电子宠物
- 拆解后续需求方向：桌宠基础能力、宠物状态系统、动画表现、轻养成、主动陪伴、情绪陪伴、陪学桌宠化和串门桌宠化
- 给出阶段路线：产品定位调整 → Web 端电子宠物化 → 桌宠 MVP → 桌宠体验增强

---

## 2026-06-30（文档：情感捕捉细化规划）

根据产品方向讨论，在 `docs/plan.md` 中新增 `[2026-06-30] Plan for 情感捕捉细化（不在前端显式展示用户心情）`。

本次仅更新规划文档，未修改业务代码。

**规划重点：**
- 明确产品约束：不在前端显式展示“用户当前心情状态”，避免用户产生被贴标签或被诊断的奇怪感
- 将情感理解定位为后端内部决策信号，用于优化宠物回复、记忆沉淀、主动关怀和亲密度计算
- 规划将当前 `reply + emotion` 结构升级为 `reply + emotion + need + intensity + risk_level`
- 新增情感需求维度 `need`，覆盖陪伴、倾诉、认可、鼓励、建议、安抚、转移注意力、庆祝、梳理、危机支持等场景
- 规划基础风险等级 `risk_level`，为自伤/极端负面等高风险表达预留安全回应策略
- 明确前端不做心情标签展示，仅可在未来考虑低干扰自然语言入口，如“想吐槽一下”“想被鼓励一下”
- 拆解后端实施方向：结构化解析升级、Prompt 更新、可选落库字段、MoodAgent 结构化趋势、情感记忆压缩、安全策略和测试方案

---

## 2026-06-25（Bug 修复：LLM API 调用错误）

### 问题分析
通过日志发现三处 LLM 调用错误：

1. **`main_chat` ReadTimeout** — `chat.py:565`，MiniMax-M2.7 扩展思考模型处理完整 prompt 超过 30s 默认超时，导致主对话返回 fallback 文本。
2. **`user_profile_agent` ReadTimeout** — `user_profile_agent.py:57`，用户画像提取 30s 超时，且该调用在聊天主流程中同步 `await`，直接阻塞响应。
3. **`mood_agent` No text block** — `mood_agent.py:74`，`max_tokens=200` 过小，思考 token 消耗完毕后无剩余 token 输出文本。

### 修复内容

**`backend/routers/chat.py`：**
- `main_chat` 超时从默认 30s 改为 90s
- `user_profile_agent` 调用从同步阻塞改为 `background_tasks.add_task`，不再阻塞聊天响应

**`backend/services/mood_agent.py`：**
- `max_tokens` 从 200 改为 800，确保 extended thinking 模型思考后仍有 token 输出文本

**`backend/services/user_profile_agent.py`：**
- `_call_llm` 增加 `timeout=90.0` 参数

---

## 2026-06-22（Bug 修复：串门功能与自定义宠物头像）

### 串门功能三处修复

**1. 结束按钮在自动轮次期间被禁用（`frontend/js/app.js`）：**
- `runAutoVisitTurns` 原来把 `endBtn.disabled = true`，6 轮全部跑完才解禁，用户无法中途结束
- 改为保留 endBtn 可点击状态，改用 `_visitAborted` 中断标志，点击结束按钮立即终止循环并结束串门

**2. LLM token budget 耗尽导致串门消息为空（`backend/services/cross_pet_service.py`）：**
- 模型 `MiniMax-M2.7` 为推理模型，会先生成 thinking 块，`max_tokens=200`（visit_turn）和 `max_tokens=300`（visit_summary）远不够用，thinking 消耗全部 token 后无文本输出
- 将两处 `max_tokens` 均提升至 1024

**3. 自定义宠物 ID 格式不匹配 UUID 校验（`backend/routers/visits.py`）：**
- 自定义宠物 ID 格式为 `custom_XXXXXXXX`，而 `start_visit` 对非预置 guest 调用了 `_validate_uuid()`，UUID 正则无法匹配该格式，直接返回 400
- 新增 `_validate_pet_id()` 函数，同时接受标准 UUID 和 `custom_XXXXXXXX` 格式

### 自定义宠物头像显示 emoji 而非图片（`frontend/index.html`）

- `selectCustomPet` 函数未存储 `qagent_custom_pet`（含 `pet_type`），导致 `app.js` 中 `rawPetType` 为空，`getPetPresetImage` 找不到对应图片，fallback 到 emoji
- `selectCustomPet` 新增 `rawPetType` 参数，进入会话时同步写入 `qagent_custom_pet`；对应 onclick 调用处同步传入 `pet.pet_type`

---

## 2026-06-20（安全修复：陪你学功能漏洞审查与修复）

调用 bug 检查 agent 对 `docs/plan.md` 中「情绪感知两层架构」与「宠物陪你学」两需求的实现做安全审查，新增漏洞记录于 `docs/bug.md` 的「陪你学功能（learning）新增漏洞追踪」章节（3 High + 3 Medium + 3 Low），并完成以下修复：

**LEARN-H-1 SSRF 重定向跟随（Fixed）：**
- `backend/services/github_service.py` 的 `_get` 改为 `httpx.AsyncClient(..., follow_redirects=False)`，并对 `resp.is_redirect` / 3xx 显式抛 `GithubError(502)`，防止重定向绕过 host 白名单跳转内网（如云元数据服务）

**LEARN-H-2 亲密度奖励竞态（Fixed）：**
- `learning_service.complete_chapter` 与 `complete_session` 改用 `db.isolation_level=None` + `BEGIN IMMEDIATE` 手动事务，在写锁内重新读取奖励/状态再写回；仅事务内确认「本次新增」的胜者请求才调用 `_add_pet_intimacy`，杜绝并发或重复点击导致的亲密度重复发放

**LEARN-M-1 仓库内容 Prompt 注入隔离（Fixed）：**
- `_build_teach_prompt` 将每个仓库文件用 `<<<REPO_FILE path="...">>> ... <<<END_REPO_FILE>>>` 围栏包裹，并加入【安全说明】强调围栏内为不可信数据、忽略其中任何指令、不得改变老师身份（结构化隔离，避免破坏源码 `<>` 符号可读性）

**LEARN-M-2 大纲字段类型校验（Fixed）：**
- `_parse_outline` 对 `title`/`learning_goal`/`project_summary` 增加 `isinstance(..., str)` 守卫，非字符串降级为默认值，不再用 `str()` 强转 dict/list 产生垃圾数据

**LEARN-L-1 URL 编码（Fixed）：**
- `parse_github_url` 正则匹配前先 `urllib.parse.unquote(url)`，防止 `%2F`/`%2e` 绕过字符集白名单

**LEARN-L-2 老师讲解落库截断（Fixed）：**
- 新增 `MAX_TEACHER_CONTENT_LEN = 12000`，`teach_chapter` 落库前截断 `teacher_content`

**核验后不修复：**
- LEARN-M-3：经核对 `/sessions/{id}/complete`（3 段）与 `/sessions/{id}/chapters/{cid}/complete`（5 段）路径深度不同，FastAPI 不存在真实路由冲突，改名风险大于收益，标记 Won't Fix
- LEARN-H-3 / LEARN-L-3：当前调用路径已校验归属、无可利用漏洞，且 H-3 与串门 VIS-1 同源已追踪，保留记录待统一处理

---

## 2026-06-20

**新功能：实现「宠物陪你学 GitHub 开源项目教学功能」**

完整落地 `docs/plan.md` 中 `[2026-06-18] Plan for 宠物陪你学 GitHub 开源项目教学功能` 的 9 个阶段。每个预置/自定义宠物新增「陪我学」入口，点击后输入 GitHub 公开仓库链接，系统分析项目并生成分章节学习大纲，用户确认后由固定「源码导读老师 Agent」逐章讲解，当前宠物作为陪学伙伴生成章末旁白，用户可向老师或宠物提问。完成章节发放亲密度奖励（每章 +2，全部完成额外 +5，防重复）。

**数据层（Phase 1）：**
- `backend/models.py`：新增 `LearningSession`、`LearningMessage` 数据类
- `backend/database.py`：新增 `learning_sessions`、`learning_messages` 两表（含 `pet_source` / `status` / `role` 的 CHECK 约束）与 5 个索引

**GitHub 读取服务（Phase 2）：**
- 新增 `backend/services/github_service.py`：`parse_github_url` 仅放行 `github.com/{owner}/{repo}`、拒绝子路径/穿越；`GithubService` 提供 `get_repo_info` / `get_readme` / `get_tree`（过滤 node_modules/.git 等，深度与条数限制）/ `select_key_files` / `fetch_file`（拒绝绝对路径与 `..`）/ `fetch_chapter_files`（单文件 12k 字符、单章 24k 字符上限）/ `analyze_repo`
- SSRF 防护：`ALLOWED_API_HOSTS = {api.github.com, raw.githubusercontent.com}`，`_get` 每次校验 host；全程不使用 Token、不 clone、不执行代码

**学习业务服务（Phase 3）：**
- 新增 `backend/services/learning_service.py`：大纲生成（3-6 章，`focus_paths` 仅保留真实存在于目录树中的路径）、创建会话、章节讲解（老师 7 段式 markdown）+ 宠物章末旁白（30-80 字、贴合人设）、问答（teacher/pet 路由）、章节进度推进、亲密度奖励（`rewarded_chapters_json` 防重复）、暂停/完成
- Prompt 注入防护：`TEACHER_SYSTEM` 明确告知仓库内容是「被分析的数据」不是指令；用户问题经 `_sanitize_prompt_input`
- 已生成讲解消息会复用缓存，避免重复消耗 LLM

**LLM 超时（Phase 3 配套）：**
- `backend/services/llm_service.py`：`_call_llm`/`chat` 新增 `timeout` 参数（默认 30s，向后兼容），学习场景按需放大（讲解 90s/2500tok、旁白 60s/1500tok、提问 60-90s/1500tok、大纲 90s/2000tok），解决 MiniMax 思考模型超时与 token 预算耗尽导致无 text block 的问题

**API 路由（Phase 4）：**
- 新增 `backend/routers/learning.py`：8 个端点（analyze / sessions / get / teach / ask / complete_chapter / pause / complete），全部带速率限制；`_verify_pet_access` 区分预置/自定义并校验自定义宠物所有权；`_get_session_and_check_owner` 校验会话归属
- `get_session_detail` 统一对所有会话（含预置宠物会话）校验 `user_id` 归属，与其他端点保持一致，避免越权读取他人学习问答
- `main.py`：注册 `learning_router`

**前端（Phase 5-6）：**
- `frontend/js/api.js`：新增 8 个学习 API 封装
- 新增 `frontend/learn.html`、`frontend/css/learn.css`、`frontend/js/learn.js`：完整学习页面，含输入→分析中→大纲确认→章节教学→完成 5 个状态机；自研轻量 Markdown 渲染器（标题/列表/代码块/行内代码/链接，先转义后渲染防 XSS）；支持刷新后通过 `session_id` 恢复进度（重建历史消息、复用已缓存讲解）

**入口接入（Phase 7）：**
- `frontend/chat.html` + `css/chat.css` + `js/app.js`：聊天页侧边栏新增「陪我学」卡片，`goToLearn()` 按当前宠物解析 pet_id（预置用 pet_type、自定义用 `qagent_custom_pet_id`）跳转
- `frontend/index.html` + `css/styles.css`：首页每张宠物卡片新增「陪我学」按钮；自定义宠物跳转前将名称/头像/pet_type 写入 localStorage 供学习页解析陪学伙伴

**验证（Phase 8-9）：**
- Python 与 JS 语法校验通过；`import main` 确认 8 条路由全部注册；数据库初始化确认两表与索引就位
- 对真实仓库 `supabase/supabase` 端到端实测：analyze 生成 6 章大纲、teach 生成 7504 字讲解 + 宠物旁白、ask teacher/pet 均正常、complete_chapter 防重复（首次 +2、重复 0）、complete_session 防重复（首次 +15、重复 `bonus_already_granted=True`）全部通过
- 新增 `test_learning_ownership.py` 覆盖跨用户归属校验：用户 B 访问用户 A 的会话（get detail / teach / ask / complete_chapter / pause / complete 六个端点）均返回 403，用户 A 本人可读，非法 session_id 格式返回 400
- 注入/越权实测：gitlab 链接、内网元数据 IP、缺 owner/repo 均返回 400；非法 `pet_id`（非预置且非合法 UUID）返回 400；`target` 非 teacher/pet 返回 422；超长提问（>1000 字符）返回 422

**安全边界已落实：** 用户归属与自定义宠物所有权校验、会话归属校验、SSRF host 白名单、URL/路径穿越防护、各字段长度上限、Prompt 注入防护、亲密度奖励防重复、8 端点全部限流。

---

## 2026-06-18

**文档：新增“宠物陪你学 GitHub 开源项目教学功能”需求计划**

在 `docs/plan.md` 中追加新需求 `[2026-06-18] Plan for 宠物陪你学 GitHub 开源项目教学功能`，本次仅进行需求拆解与开发计划记录，未修改业务代码。

**已确认方向：**
- 每个预置/自定义宠物新增“陪我学”入口
- 点击后进入新的学习页面，而不是复用聊天页弹窗
- 当前 MVP 只支持 GitHub 公开开源项目
- 先生成并展示学习大纲，用户确认后开始教学
- 老师采用固定“源码导读老师 Agent”，通过动态注入项目信息适配不同项目
- 宠物采用“章末旁白”互动方式，不随机打断老师讲解

**开发任务拆解覆盖：**
- 数据模型与数据库迁移：`learning_sessions`、`learning_messages`
- GitHub 仓库读取服务：URL 校验、README、目录树、关键文件读取
- 学习业务服务：大纲生成、章节讲解、宠物旁白、问答、进度与亲密度奖励
- 学习 API 路由：分析仓库、创建会话、章节教学、提问、暂停、完成
- 前端 API 封装与新页面：`learn.html`、`learn.css`、`learn.js`
- 首页/聊天页宠物入口接入
- 安全边界：用户归属校验、SSRF 防护、内容长度限制、Prompt 注入防护、限流
- 测试与验收标准

---

## 2026-06-17

**安全修复：按 `docs/bug.md` 修复主安全、串门、情绪架构漏洞**

本次集中修复 `docs/bug.md` 中 Open/Partial 状态的漏洞，采用最小侵入式策略（保留现有 `X-User-Id` + API Key 认证模型，强化校验与归属检查）。

**情绪架构修复（EMO-*）：**
- `backend/services/memory_service.py`
  - 新增 `ALLOWED_PROFILE_FIELDS` 白名单与字段名正则校验，修复 `merge_user_profile` 动态 SQL 字段名 SQL 注入风险（EMO-C-1）
  - 新增按字段长度上限截断（`FIELD_MAX_LEN`），修复 `user_profiles` 字段无限增长问题（EMO-H-4）
  - 将 SELECT 与 UPDATE 合并到同一事务，修复并发覆盖问题（EMO-M-3）
- `backend/services/mood_agent.py`
  - `should_trigger` 改为同步函数，并增加 `total_chats >= 5` 守卫，避免首条消息触发空历史分析（EMO-H-1 / EMO-L-1）
  - `analyze_mood_tendency` 中对用户消息调用 `_sanitize_prompt_input()`，修复二阶 Prompt 注入（EMO-M-2）
  - 增加 `session_id` UUID 格式校验（EMO-L-3）
- `backend/services/llm_service.py`
  - `_clean_response` 仅匹配顶层 `thought` / `reasoning` JSON 键，避免误删正常回复内容（EMO-H-2）
  - `LLM_API_KEY` 不再保存在实例属性中，调用时从 `settings` 读取（H-2）
- `backend/routers/chat.py`
  - `parse_structured_reply` 增加 None/空字符串守卫；正则兜底改为从后向前匹配，优先取最外层 JSON（EMO-M-1 / EMO-M-4）
  - 工具路径二次 LLM 的情绪标签被正确捕获并覆盖首轮情绪（EMO-H-3）
  - 两处日常分享概率改为 `random.random() < 0.33`（EMO-L-4）
  - 路由层增加 `session_id` UUID 格式校验（EMO-L-3）

**串门功能修复（VIS-*）：**
- `backend/routers/visits.py`
  - 非预置 `guest_pet_id` 增加所有权校验，不匹配返回 403（VIS-1）
  - 所有 5 个端点补充 `@limiter.limit(...)` 速率限制（VIS-3）
  - `start_visit` 将 active visit 检查与 INSERT 合并到同一事务，修复 TOCTOU（VIS-5）
  - `next_turn` 增加 persona None 保护（VIS-7）
  - `list_visits` 改为批量查询宠物名称，消除 N+1（VIS-8）
  - Schema 增加 `topic` / `user_interjection` 长度限制（VIS-2）
- `backend/services/cross_pet_service.py`
  - `build_visit_prompt` 对 `topic` / `user_interjection` 调用 `_sanitize_prompt_input()`（VIS-2）
  - `generate_visit_turn` 在单事务内检查消息数上限，服务层兜底 20 条限制（VIS-4 / VIS-5）
  - `end_visit` 写入 guest 记忆前验证 `guest_session_id` 归属（VIS-6）

**主安全与配置加固：**
- `backend/auth.py`
  - 增加 `X-User-Id` 格式校验（1-64 位字母数字下划线连字符），非法时返回 400（C-1 / M-3）
  - 认证错误改为直接返回 `JSONResponse`，避免中间件内 `HTTPException` 变为 500
- `backend/config.py` / `.env.example`：CORS 默认值从 `*` 改为本地开发域名，降低生产误配风险（H-1）
- `render.yaml`：新增 `CORS_ORIGINS` 与 `API_KEY` 环境变量占位（H-1 / OPT-M-5）
- `backend/database.py`：数据库初始化后调用 `os.chmod(path, 0o600)` 限制数据库文件权限（L-1）
- `backend/routers/sessions.py`、`backend/routers/custom_pets.py`：为关键端点补充 `@limiter.limit(...)` 限流（M-2）
- `backend/services/embedding_service.py`：`EMBEDDING_API_KEY` 不再保存在实例属性中，调用时从 `settings` 读取（H-2）

**验证结果：**
- ✅ `python -m py_compile` 全量文件语法检查通过
- ✅ `python test_memory_integration.py` 通过
- ✅ 本地服务启动正常，健康检查 `/health` 返回 200
- ✅ 非法 `X-User-Id` 返回 400
- ✅ 聊天接口返回正常响应与情绪标签
- ✅ 串门接口 5 次/分钟限流生效（第 6 次返回 429）
- ✅ 非归属自定义宠物作为 guest 返回 403
- ✅ 非法 `session_id` 格式返回 400

---

## 2026-06-17

**文档：bug.md 已修复bug清理**

清理 `docs/bug.md` 中已修复bug的详细内容，仅保留标题：
- **OPT-H-1** 认证机制跳过模式/路由硬编码user_id → 状态已为 Fixed，删除详细描述，保留"已修复bug"标题
- **OPT-M-3** 数据库迁移宽泛try-except静默吞错 → 状态已为 Fixed，删除详细描述，保留"已修复bug"标题

未修复的bug（Open/Partial状态）保持原样不变。

---

## 2026-06-17

**功能：情绪感知两层架构重构**

将阻塞式独立 LLM 情绪识别调用重构为两层架构，消除一次额外的 LLM 调用，同时新增后台情绪趋势分析 Agent。

**前台层（主 LLM 结构化输出）：**
- `backend/routers/chat.py`
  - 新增 `parse_structured_reply(raw: str) -> tuple[str, str]` 辅助函数，解析 LLM 的 JSON 结构化输出；支持直接解析和正则兜底，失败时降级为 `(raw, "neutral")`
  - `full_prompt` 末尾指令从"直接输出回复内容"改为要求 LLM 输出 `{"reply": "...", "emotion": "..."}` JSON，emotion 取值限定为 `happy/sad/anxious/tired/neutral`
  - `execute_tools_and_build_final_prompt` 的 `second_prompt` 末尾同步改为 JSON 格式要求，二次 LLM 返回值通过 `parse_structured_reply` 解析（工具轮次忽略 emotion，只取 reply）
  - 主 LLM 调用后直接从 `parse_structured_reply` 获取 `emotion_tag`，删除原 `llm_service.extract_emotion(sanitized_content, pet_type)` 独立阻塞调用
  - 新增 `from fastapi import BackgroundTasks` 和 `from backend.services.mood_agent import mood_agent` 导入
  - `chat` 函数签名追加 `background_tasks: BackgroundTasks` 参数
  - 在 `return ChatResponse` 前注册后台情绪趋势分析任务（每 5 轮触发一次）

**后台层（MoodAgent）：**
- `backend/services/mood_agent.py`（新建）
  - 实现 `MoodAgent` 类，含 `should_trigger`（基于 `total_chats % 5 == 0`）和 `analyze_mood_tendency` 方法
  - `analyze_mood_tendency`：读取 session 最近 15 条 `role=user` 消息，调用轻量 LLM（`caller="mood_agent"`），将 ≤20 字情绪倾向描述写入 `user_profiles.mood_tendency`（通过 `memory_service.merge_user_profile`）
  - 所有异常均被 `try/except` 捕获，不影响主响应路径
  - 导出全局单例 `mood_agent`

**清理 user_profile_agent：**
- `backend/services/user_profile_agent.py`
  - 从 `PROFILE_EXTRACT_PROMPT` 说明列表中删除第 7 条"情绪倾向"
  - 从 JSON schema 示例中删除 `"mood_tendency"` 字段
  - `mood_tendency` 字段的更新权交由 `MoodAgent` 独占，避免竞争写入

**未变更：**
- `backend/services/llm_service.py` 中的 `extract_emotion` 方法保留，只是不再从 `chat.py` 调用
- `ChatResponse.emotion_tag` 字段不变，来源从 `extract_emotion` 改为 `parse_structured_reply` 第二返回值
- 前端零改动

---

## 2026-06-17

**修复：user_profile_agent No text block 报错**

- `backend/services/user_profile_agent.py`：`max_tokens` 从 300 调整为 2000，避免 MiniMax extended thinking 模型在 thinking 阶段耗尽 token 预算、无法生成 text 块
- `backend/services/llm_service.py`：将"只有 thinking 块、没有 text 块"场景的 `logger.error` 降级为 `logger.warning`，并补充 `"token budget likely exhausted"` 提示，使日志信息更准确

---

## 2026-06-17

**前端：圆润可爱风格全面重设计**

将全局视觉风格从「玻璃拟态营销风」转变为「圆润可爱」(Round & Cute) 设计语言，全面简化视觉、布局和交互，保留所有已有功能。

**设计方向变更：**
- 移除所有 `backdrop-filter: blur()` 和半透明玻璃效果
- 背景从多层 `radial-gradient` 改为纯色暖奶油色（`#fef6ee`）
- 卡片从半透明改为纯白实底，统一大圆角（20-28px）
- 头像从圆角方形改为正圆形，加彩色描边环
- 按钮统一为药丸形（`border-radius: 999px`），悬停效果改为 `scale(1.04)` 弹性缩放
- 移除所有装饰性 `::before`/`::after` 伪元素
- 统一 CSS 变量设计令牌系统

**页面级变更：**
- `frontend/index.html`
  - 移除营销式 Hero 面板（含 eyebrow、meta cards、story/tip cards）
  - 替换为紧凑型 welcome header（标题 + 副标题 + 创建按钮）
  - 宠物卡片网格直接展示，无需滚动过 Hero
- `frontend/chat.html`
  - 移除 chat-kicker 标签，简化标题区
  - 输入提示改为「💬 聊得越多，它越懂你」
  - 侧边栏结构保持不变，视觉降噪
  - 串门、记忆面板、画像编辑功能完整保留
- `frontend/custom_pet.html`
  - 移除大号 builder-headline，替换为紧凑标题「🐾 创建你的专属宠物」
  - 预览面板标题简化
  - 表单结构、实时预览、所有内联 JavaScript 完整保留

**CSS 重写：**
- `frontend/css/styles.css` — 全局令牌 + 首页样式全面重写
- `frontend/css/chat.css` — 聊天页样式全面重写
- `frontend/css/custom_pet.css` — 创建页样式全面重写

**文件清理：**
- 删除 `frontend/js/custom_pet.js`（过期未使用，引用了不存在的 DOM 元素）

**未变更：**
- `frontend/js/api.js` — 无改动
- `frontend/js/app.js` — 无改动（所有 DOM 查询 ID 保持兼容）
- 后端代码 — 无改动
- 所有功能 — 完整保留（聊天、记忆面板、画像编辑、串门、模拟控制、自定义宠物 CRUD）

---

## 2026-06-16

**前端：统一视觉风格并重做核心页面体验**

本次聚焦前端界面美化与交互细节补强，统一首页、聊天页、自定义宠物页的视觉语言，提升层次感、品牌感和移动端可用性。

**项目分析结论：**
- 当前项目为前后端分离结构：`backend/` 提供 FastAPI 路由与宠物/记忆/串门等服务，`frontend/` 采用原生 `HTML + CSS + JavaScript`
- 前端核心页面集中在 `frontend/index.html`、`frontend/chat.html`、`frontend/custom_pet.html`
- 原有问题主要在于：视觉风格分裂、层级较弱、页面信息密度不均、移动端体验一般，以及部分交互细节未与 UI 联动

**本次前端改动：**
- `frontend/css/styles.css`
  - 重建首页及全局视觉基座：暖色渐变背景、玻璃拟态面板、统一圆角/阴影/配色变量
  - 重做宠物卡片、Hero 区、空状态、按钮和 loading 样式
- `frontend/index.html`
  - 重构首页布局，增加品牌 Hero、产品价值说明和预设宠物卡片说明
  - 优化自定义宠物卡片的动态插入结构，使其与新设计一致
- `frontend/css/custom_pet.css`
  - 将创建页改为左侧配置、右侧实时预览的双栏结构
  - 重做宠物类型选择、性格标签、头像上传、按钮和预览区样式
- `frontend/custom_pet.html`
  - 移除大段内联样式，改为结构化页面
  - 增加实时预览卡片、顶部返回入口和更清晰的表单分区文案
- `frontend/css/chat.css`
  - 重做聊天页整体布局、侧边栏、消息气泡、输入区、记忆面板和串门弹层样式
  - 优化平板/手机断点下的布局，保留侧边功能可访问性
- `frontend/chat.html`
  - 重构聊天页 DOM 结构，补充标题、副标题、输入提示和更清晰的串门入口
- `frontend/js/app.js`
  - 新增亲密度环形进度联动 `syncIntimacyRing()`
  - 新增输入框自适应高度 `autoResizeTextarea()`
  - 根据当前宠物动态同步主题色到 CSS 变量
  - 调整宠物状态文案，使 UI 显示与新视觉风格一致

**结果：**
- 首页更像产品落地页，而非简单卡片列表
- 创建页具备更强的“角色编辑器”感
- 聊天页层次更清晰，视觉统一，并补上了之前缺失的亲密度环联动

---

## 2026-06-16（第二次）

**修复：根路径未指向前端页面，导致浏览器打开 8080 后只看到 API 响应**

排查发现前后端端口本身是通的，问题不在端口连通性，而在服务入口配置：

- `main.py` 将前端静态资源挂载在 `/frontend`
- 根路径 `/` 之前返回的是后端 JSON：`{"message": "QAgent Pet API is running", "version": "1.0.0"}`
- 因此直接打开 `http://127.0.0.1:8080/` 不会进入前端首页，必须手动访问 `/frontend/index.html`

**本次修复：**
- `main.py`
  - 引入 `RedirectResponse`
  - 将根路径 `/` 改为 `307` 重定向到 `/frontend/index.html`

**结果：**
- 现在直接打开 `http://127.0.0.1:8080/` 会进入前端首页
- 前端页面通过同源 `/api/...` 请求后端接口，前后端端口链路保持一致

---

## 2026-06-15（安全审计）

**安全审计：串门功能（visits）漏洞发现**

对 2026-06-15 实现的宠物 Agent 串门通信功能进行安全审计，在 `docs/bug.md` 中新增以下漏洞追踪（VIS-1 ~ VIS-8）：

- **VIS-1（High）**：`start_visit` 未校验 `guest_pet_id` 所有权，攻击者可用他人宠物 ID 发起串门，间接读取他人宠物 `system_prompt`
- **VIS-2（High）**：`topic` 和 `user_interjection` 字段直接拼入 Prompt，未调用 `_sanitize_prompt_input()`，且 `topic` 无长度限制，存在 XML 结构注入风险
- **VIS-3（High）**：`visits.py` 全部 5 个端点缺少 `@limiter.limit()` 装饰器，串门接口可被无限循环调用耗尽 LLM 配额
- **VIS-4（Medium）**：20 条消息上限仅在路由层检查，服务层 `generate_visit_turn` 无保护
- **VIS-5（Medium）**：active visit 唯一性检查和消息数检查均存在 TOCTOU 竞争条件
- **VIS-6（Medium）**：`end_visit` 写入 guest 记忆前缺乏独立所有权验证
- **VIS-7（Low）**：`next_turn` 和 `list_visits` 对 None persona 无空指针保护，宠物被删除后接口 500
- **VIS-8（Low）**：`list_visits` 存在 N+1 查询

---

## 2026-06-15

**功能：宠物 Agent 串门通信（Phase 1 + Phase 2）**

实现了两只宠物互相"串门"对话的完整功能，包含核心功能和记忆沉淀。

**后端变更：**

- `backend/database.py`：新增 `pet_visits`、`pet_visit_messages` 两张表及相关索引（`init_database` 中追加，兼容已有数据库）
- `backend/models.py`：新增 `PetVisit`、`PetVisitMessage` dataclass
- `backend/services/cross_pet_service.py`（新建）：实现 `CrossPetService`，包含：
  - `get_pet_persona`：统一获取预置/自定义宠物人格
  - `build_visit_prompt`：构建上下文隔离的串门专用 Prompt（XML 结构）
  - `generate_visit_turn`：驱动一次发言 Turn，写入 `pet_visit_messages`
  - `end_visit`：结束串门，生成摘要并写入双方 `long_term_memories`
- `backend/routers/visits.py`（新建）：5 个路由，prefix `/api/visits`
  - `POST /api/visits`：发起串门（自动终止同一 host session 的旧 active visit）
  - `POST /api/visits/{id}/next`：驱动下一 Turn，支持指定 speaker 和用户插话
  - `GET /api/visits/{id}/messages`：获取串门消息列表
  - `POST /api/visits/{id}/end`：结束串门，触发记忆沉淀
  - `GET /api/visits`：获取用户历史串门列表
- `main.py`：注册 `visits_router`

**安全和边界处理：**
- 每个 visit 的消息数硬限制 ≤20 条
- 并发控制：同一 host_session_id 最多 1 个 active visit，新建前自动终止旧的
- LLM 超时 fallback：返回"……{宠物名}想了想，好像不知道说什么"
- 角色混淆后处理：检测并移除回复中的"对方名字:" 前缀

**前端变更：**
- `frontend/js/api.js`：新增 `startVisit`、`nextVisitTurn`、`endVisit`、`listVisits` 四个 API 函数
- `frontend/chat.html`：聊天工具栏新增"串门"按钮（动态显示）；主聊天区内嵌串门面板（半透明叠加）；选择串门宠物的 Modal
- `frontend/css/chat.css`：新增串门相关样式（面板、气泡、控制栏、选择 Modal）
- `frontend/js/app.js`：新增 `ChatApp` 方法：
  - `initVisitFeature`：初始化检测是否显示串门按钮
  - `openVisitModal`：打开宠物选择 Modal
  - `startVisit`：发起串门
  - `runAutoVisitTurns`：自动循环最多 6 轮（可带插话）
  - `endVisit`：结束串门并触发记忆写入

**已验证：需求1（自定义宠物开场白 LLM 生成）**

经代码审查确认，`backend/prompts/custom_pet.py` 的 `generate_welcome_messages()` 已于更早的迭代中改为调用 `llm_service.generate_custom_welcome_message()`，保留 fallback 模板，无需修改。

---

## 2026-06-14（第四次）

**文档：新增宠物 Agent 串门通信技术方案**

在 `docs/plan.md` 中追加新章节 `[2026-06-14] Plan for 宠物 Agent 串门通信`，不涉及任何业务代码修改。

**方案内容：**
- 可行性评估：结论为可行，难度中等，三阶段交付
- 核心交互模型：中心化协调器模式，由后端 `CrossPetService` 轮流驱动两个宠物 LLM 对话
- 上下文隔离设计：`<system>` 只注入发言宠物自身人格，对方宠物信息降级为 ≤50 字的 `<visit_context>` 段落
- 新增数据表：`pet_visits`（串门元信息）、`pet_visit_messages`（串门发言记录）
- 新增 API：5 个端点，prefix `/api/visits`
- 新增服务：`backend/services/cross_pet_service.py`（`CrossPetService`）
- 前端：`chat.html` 串门面板、`api.js` 3 个串门函数
- 边界情况：8 类场景及处理方案
- 分阶段交付：Phase 1（核心互访）→ Phase 2（记忆沉淀）→ Phase 3（跨用户联机，远期）

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

