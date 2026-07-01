# QAgent Pet 需求计划

---

需求：口头禅概率控制已实现。

需求：自定义宠物持久化存储已实现。

需求：自定义宠物删除功能已实现。

需求：自定义宠物开场白 LLM 生成已实现。

需求：宠物 Agent 串门通信（Phase 1 核心功能 + Phase 2 记忆沉淀）已实现。

---

需求：情绪感知两层架构重构已实现。

---

已实现需求：宠物陪你学 GitHub 开源项目教学功能。

---

## [2026-06-30] Plan for 情感捕捉细化（不在前端显式展示用户心情）

### Requirement

在保持当前前端聊天体验自然、不直接向用户展示“系统判断你现在是什么心情”的前提下，增强后端对用户情感状态与情感需求的捕捉能力，让宠物回复更贴近用户真实需求。

关键产品约束：

1. **不在前端界面显式展示用户当前心情状态**。
   - 不新增类似“你当前心情：焦虑/低落”的明显 UI。
   - 避免让用户产生被系统贴标签、被观察或被诊断的奇怪感。
2. **情感理解只作为后端决策信号使用**。
   - 用于优化宠物回复方式、记忆沉淀、主动关怀策略、亲密度计算。
   - 前端可保留自然聊天体验，不把内部判断直接暴露给用户。
3. **优先细化“情感需求”而非做情绪可视化**。
   - 目标不是让用户看到情绪标签，而是让宠物更会陪、更少误判、更符合当下需求。

### Design Overview

当前聊天主 LLM 结构化输出为：

```json
{"reply": "宠物回复", "emotion": "happy/sad/anxious/tired/neutral"}
```

规划升级为内部情感理解结构：

```json
{
  "reply": "宠物回复",
  "emotion": "sad",
  "need": "companionship",
  "intensity": 3,
  "risk_level": "none"
}
```

字段说明：

| 字段 | 类型 | 用途 | 是否前端展示 |
|------|------|------|--------------|
| `reply` | string | 宠物最终回复内容 | 是 |
| `emotion` | enum | 用户当前基础情绪 | 否，内部使用 |
| `need` | enum | 用户此刻更可能需要的情感支持方式 | 否，内部使用 |
| `intensity` | int 1-5 | 情绪强度，用于调整回复力度和主动关怀 | 否，内部使用 |
| `risk_level` | enum | 危机/敏感风险等级 | 否，内部使用；高风险时影响回复策略 |

### 情绪维度（emotion）

第一阶段保持兼容现有 5 类，同时可扩展更多细粒度标签：

- `happy`：开心、愉快
- `sad`：低落、难过
- `anxious`：焦虑、紧张
- `tired`：疲惫、耗竭
- `neutral`：中性/无法判断

后续可选扩展：

- `lonely`：孤独、缺少陪伴
- `stressed`：压力大
- `angry`：生气、委屈
- `confused`：迷茫、不知所措
- `ashamed`：自责、羞耻
- `excited`：兴奋、期待

### 情感需求维度（need）

新增 `need` 字段，用于判断用户此刻更需要哪种陪伴，而不是只判断“是什么情绪”。

建议枚举：

| need | 含义 | 宠物回复策略 |
|------|------|--------------|
| `companionship` | 需要陪伴 | 少说教，表达“我在这里”，允许沉默和慢慢说 |
| `venting` | 需要倾诉 | 鼓励继续说，少给建议，多接住情绪 |
| `validation` | 需要被认可 | 先承认感受合理，减少否定和纠正 |
| `encouragement` | 需要鼓励 | 给信心、肯定努力，但避免强行正能量 |
| `advice` | 需要建议 | 给简短、可执行的小步骤 |
| `calming` | 需要安抚 | 引导放慢、呼吸、休息、降低紧迫感 |
| `distraction` | 需要转移注意力 | 讲轻松话题、小故事、宠物日常 |
| `celebration` | 需要一起开心 | 放大快乐、一起庆祝、增强正反馈 |
| `reflection` | 需要梳理 | 帮用户整理原因、选项和下一步 |
| `crisis_support` | 需要危机支持 | 切换安全回应策略，建议联系现实支持资源 |
| `unknown` | 暂不确定 | 保持自然回应，不强行判断 |

### 强度维度（intensity）

`intensity` 范围为 1-5：

- 1：轻微情绪，仅轻度调整语气
- 2：明显但不强烈，可温和回应
- 3：中等强度，需要明确接住情绪
- 4：强烈情绪，需要降低建议密度、更多陪伴或安抚
- 5：极强情绪，需结合 `risk_level` 判断是否进入安全策略

用途：

1. 调整回复长度和安抚强度。
2. 调整亲密度增长，不再只对 `sad` 加权。
3. 作为后台 `MoodAgent` 判断长期趋势的输入。
4. 为主动关怀触发提供依据。

### 风险等级（risk_level）

第一阶段不做复杂心理诊断，只做基础安全分级：

- `none`：无明显风险
- `low`：轻微负面、普通压力或疲惫
- `medium`：持续强烈负面、明显绝望感、失控感
- `high`：自伤/自杀/伤害他人等高风险表达

当 `risk_level == high` 时：

1. 宠物保持角色语气，但回复必须优先安全。
2. 不开玩笑，不轻描淡写，不只用口头禅糊弄。
3. 鼓励用户联系现实中可信任的人。
4. 如存在即时危险，引导用户联系当地紧急救援/报警/急救服务。
5. 明确本产品不是专业心理咨询或医疗服务。

### 前端策略

本需求明确 **不新增显式心情展示 UI**。

不做：

- 不显示“系统判断你当前心情是 sad”。
- 不显示“你现在需要陪伴/建议”。
- 不做醒目的心情状态栏。
- 不在每条消息旁展示情绪标签。

可以考虑但不强制：

- 输入框占位文案更柔和，如“想说什么都可以，我在听”。
- 提供不显眼的快捷表达按钮，如“想吐槽一下”“想被鼓励一下”“只想安静聊聊”，但点击后以自然语言进入对话，而不是显示为系统标签。
- 未来如果做反馈，也用自然措辞，例如“刚才这样回你合适吗？”而不是“情绪识别是否正确？”。

### Backend Implementation Plan

#### 1. `backend/routers/chat.py`

- 扩展 `parse_structured_reply()`：
  - 从返回值 `(reply, emotion)` 升级为更完整的结构对象，或新增 `parse_emotional_reply()`。
  - 兼容旧格式：如果 LLM 只返回 `reply/emotion`，则 `need="unknown"`、`intensity=1`、`risk_level="none"`。
- 修改主 LLM Prompt 末尾 JSON 要求：
  - 要求输出 `reply/emotion/need/intensity/risk_level`。
  - 明确这些字段是内部判断，不要在 `reply` 中直接告诉用户“你现在是某某情绪”。
- 工具调用二次 LLM 路径同步升级结构化输出。
- `ChatResponse` 第一阶段可暂不暴露新增字段，避免前端展示。
- 亲密度计算改造：从只看 `emotion_tag` 改为结合 `emotion + need + intensity`。

#### 2. `backend/schemas.py`

- 第一阶段可保持 `ChatResponse` 不变，只返回 `reply`、`emotion_tag` 等兼容字段。
- 如后续需要调试，可新增可选字段但默认不在前端使用：
  - `emotional_need: Optional[str] = None`
  - `emotion_intensity: Optional[int] = None`
  - `risk_level: Optional[str] = None`
- 是否暴露这些字段需谨慎，默认建议只内部落库。

#### 3. `backend/database.py`

可选新增字段到 `messages` 表：

- `emotional_need TEXT`
- `emotion_intensity INTEGER`
- `risk_level TEXT`

或新增独立表：

```sql
CREATE TABLE IF NOT EXISTS emotion_events (
    event_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    emotion TEXT,
    emotional_need TEXT,
    intensity INTEGER,
    risk_level TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
```

建议第一阶段优先采用 `messages` 表扩展，改动较小；后续如果做趋势分析、统计和隐私控制，再拆独立表。

#### 4. `backend/services/mood_agent.py`

- 从“最近 15 条用户消息 → 20 字情绪倾向”升级为结构化趋势分析。
- 输出可以包含：

```json
{
  "mood_tendency": "最近压力偏高，偶尔低落",
  "dominant_emotion": "anxious",
  "dominant_need": "calming",
  "suggested_support_style": "少催促，多安抚，帮助拆小步骤"
}
```

- 写入用户画像时仍可只写 `mood_tendency`，其他字段后续再扩展。

#### 5. `backend/services/memory_service.py`

- 长期记忆压缩 Prompt 增加要求：
  - 保留用户重要情绪事件。
  - 保留用户表达过的支持偏好。
  - 保留用户的压力来源、触发因素和有效安抚方式。
- 情感类记忆可以提高 `importance`，降低被时间衰减影响的速度。

#### 6. `backend/prompts/*.py` 与 `backend/prompts/custom_pet.py`

- 更新宠物 Prompt：
  - 不要求宠物直接说“我判断你是 sad”。
  - 要求宠物根据 `need` 选择回应方式。
  - 强调“先接住情绪，再考虑建议”。
- 自定义宠物后续可增加“情感支持偏好”配置，但本阶段先不做前端表单改动。

### Safety Strategy

新增基础安全规则：

1. 对 `risk_level=high` 的消息，优先使用安全回应框架。
2. 高风险场景下禁用轻浮口吻、随机日常分享和过度玩笑。
3. 宠物可以保持人格，但必须表达认真、陪伴和现实求助建议。
4. 避免把本产品包装成专业心理咨询。

### Testing Strategy

- `parse_emotional_reply` 单元测试：
  - 新格式完整 JSON。
  - 旧格式 `reply/emotion` 兼容。
  - 非法 `need` 降级为 `unknown`。
  - 非法 `intensity` 降级到 1-5 合法范围。
  - 非法 `risk_level` 降级为 `none`。
  - 纯文本 fallback 不影响回复。
- 聊天接口测试：
  - LLM 返回 `need=companionship` 时回复正常。
  - LLM 返回 `risk_level=high` 时进入安全策略。
  - 前端响应不新增明显心情展示字段依赖。
- 记忆测试：
  - 情感事件能够被压缩进入长期记忆。
  - 支持偏好不被普通事实摘要覆盖。

### Rollout Plan

1. **Phase 1：内部结构升级**
   - 扩展 LLM JSON 输出与解析。
   - 保持前端无明显变化。
   - 新字段仅用于日志/数据库/亲密度。

2. **Phase 2：回复策略优化**
   - 根据 `need/intensity` 调整宠物回复 Prompt。
   - 加入高风险安全策略。
   - 优化长期记忆中的情感事件保留。

3. **Phase 3：低干扰反馈入口**
   - 不展示“你当前心情”。
   - 可选增加自然语言快捷入口，如“想吐槽一下/想被鼓励一下”。
   - 反馈方式采用“这样回你合适吗？”而非“情绪识别是否正确？”。

### Open Questions

1. 是否需要把 `need/intensity/risk_level` 落库到 `messages`，还是先只在运行时使用？
2. 高风险安全策略是否采用固定模板，还是仍由 LLM 在安全规则约束下生成？
3. 自定义宠物是否需要新增“陪伴偏好”配置项，还是先通过对话自动学习？
4. 亲密度是否应根据 `intensity` 和 `need` 重新设计为更细的成长规则？

---

## [2026-07-01] Plan for 产品转型阶段化落地

### Requirement

基于 `docs/产品转型方向文档.md` 及现有需求计划，将项目从“QQ 智能宠物伴侣 Agent”逐步转型为“个人 AI 电子宠物伴侣”。

转型后的产品主线：

- **QAgent Pet Core**：复用现有 FastAPI 后端，作为统一宠物智能核心。
- **Web 端**：完整功能中心，承载聊天、记忆、学习、串门、自定义宠物等完整能力。
- **桌宠端**：下一阶段重点入口，提供桌面常驻、气泡聊天、主动陪伴、提醒与快速打开 Web 面板。
- **QQ/IM 入口**：从当前主线降级为远期可选扩展，不作为短期核心依赖。

核心差异化：不与通用 AI 助手竞争效率问答，而是主打“关系型 AI 电子宠物”：长期记忆、主动关怀、人格连续性、轻养成、陪伴感。

### Overall Roadmap

```text
Phase 0 情感捕捉细化
  → Phase 1 产品定位调整 + Web 端电子宠物化
  → Phase 2 桌宠 MVP
  → Phase 3 桌宠体验增强 + 养成体系
  → Phase 4 QQ/IM/移动端扩展
```

优先级：**Phase 0 > Phase 1 > Phase 2 > Phase 3 > Phase 4**。

---

### Phase 0：情感捕捉细化

#### Goal

完成当前已规划的情感理解升级，为宠物状态系统、主动关怀、长期记忆和桌宠行为决策提供结构化信号。

#### Deliverables

1. 主 LLM 结构化输出升级为：

   ```json
   {
     "reply": "宠物回复",
     "emotion": "sad",
     "need": "companionship",
     "intensity": 3,
     "risk_level": "none"
   }
   ```

2. 后端解析函数兼容新旧格式：
   - 新格式：`reply/emotion/need/intensity/risk_level`。
   - 旧格式：`reply/emotion`。
   - 异常格式：回复 fallback 为原始文本，情感字段降级为安全默认值。
3. `risk_level=high` 时进入高风险安全回应策略。
4. `MoodAgent` 从简单情绪趋势分析升级为结构化趋势分析。
5. 亲密度计算从只依赖 `emotion_tag` 升级为结合 `emotion + need + intensity`。
6. 前端不显式展示用户心情，保持自然聊天体验。

#### Main Files / Modules

- `backend/routers/chat.py`
- `backend/services/mood_agent.py`
- `backend/services/memory_service.py`
- `backend/database.py`
- `backend/schemas.py`
- `backend/prompts/*.py`
- `backend/prompts/custom_pet.py`

#### Acceptance Criteria

- LLM 返回完整 5 字段 JSON 时能正确解析。
- LLM 返回旧格式或纯文本时不影响聊天主流程。
- 非法 `need/intensity/risk_level` 能正确降级。
- `risk_level=high` 时回复不再走普通玩笑/口头禅路径，优先安全回应。
- 前端不新增醒目的“当前心情”展示。
- 单元测试覆盖解析、fallback、高风险策略和亲密度计算。

---

### Phase 1：产品定位调整 + Web 端电子宠物化

#### Goal

统一产品叙事，并先在 Web 端验证“电子宠物感”，让 Web 从单纯聊天网页升级为完整宠物功能中心。

#### Deliverables

1. 文档定位更新：
   - README、需求文档、产品说明中统一使用“个人 AI 电子宠物伴侣”。
   - QQ/IM 描述改为可选入口，而不是唯一主线。
2. Web 端宠物状态组件：
   - 状态示例：`idle / happy / lonely / sleepy / studying`。
   - 状态来源优先结合最近互动、情感信号、学习模式和亲密度。
3. 简单宠物动画：
   - MVP 阶段使用图片 + CSS 动画。
   - 暂不引入 Live2D，避免复杂度过早上升。
4. 轻养成信息面板：
   - 今日互动次数。
   - 陪伴时长。
   - 连续互动天数。
   - 亲密度/关系等级。
5. 桌宠模式入口或预览页：
   - 让用户理解后续桌宠形态。
   - 可复用未来桌宠 UI 的最小组件。
6. 文案调整：
   - 从“聊天 AI / QQ Agent”转向“电子宠物陪伴 / 你的桌面伙伴”。

#### Main Files / Modules

- `docs/README.md`
- `docs/QAgent_Pet_需求实现文档.md`
- `docs/产品转型方向文档.md`
- `frontend/chat.html`
- `frontend/css/chat.css`
- `frontend/js/app.js`
- 可新增 `frontend/desktop_pet_preview.html`

#### Acceptance Criteria

- 文档中 QQ 不再作为唯一产品主线。
- Web 端能看到宠物当前状态或状态动画。
- 轻养成数据能与现有消息记录、亲密度、学习数据联动。
- 不破坏现有聊天、学习、串门、自定义宠物功能。
- 桌宠入口/预览能清晰表达下一阶段方向。

---

### Phase 2：桌宠 MVP

#### Goal

用 Electron 快速验证桌面常驻陪伴形态，跑通“桌面常驻 + 气泡聊天 + 主动提醒 + 打开 Web 面板”的最小闭环。

#### Deliverables

1. 新增 Electron 桌宠工程：
   - 建议目录：`desktop/`。
   - 包含 `main.js`、`preload.js`、`renderer/` 等基础结构。
2. 透明无边框置顶窗口：
   - 支持拖拽移动。
   - 支持关闭到系统托盘。
3. 点击宠物弹出聊天气泡：
   - 发送用户输入。
   - 调用现有聊天 API。
   - 展示 LLM 思考态与回复气泡。
4. 桌面情境提醒气泡（MVP 轻量版）：
   - 气泡只承担“提醒宠物发消息了/想互动”的提示职责，不直接呈现完整回复内容，避免桌面打扰和隐私暴露。
   - 气泡文案采用 2 个字左右的极短概括，用于表达宠物当前心情或本次消息主题，例如“找你”“想你”“等待”“无聊”“鼓励”“提醒”。
   - 用户点击气泡或宠物后再展开完整聊天面板，查看完整问候、回复或主动关怀内容。
   - MVP 阶段只使用低敏桌面情境信号，例如当前时间段、最近互动时间、后端情感趋势、学习状态、勿扰模式。
   - 不读取屏幕内容、聊天窗口内容或敏感应用内容，避免隐私风险和实现复杂度过早上升。
   - 气泡应支持自动消失、用户点击展开/收起、勿扰模式下静默。
5. 主动关怀桌面气泡：
   - 基于最近互动时间、情感趋势、学习状态触发。
   - MVP 可先用简单规则。
6. 右键菜单：
   - 打开完整 Web 面板。
   - 切换勿扰/退出。
7. 后端启动与连接：
   - 检测本地后端端口。
   - 必要时自动启动后端。
   - 启动失败时给出明确提示。

#### Main Files / Modules

- `desktop/main.js`
- `desktop/preload.js`
- `desktop/renderer/`
- `frontend/desktop_pet.html`
- `frontend/css/desktop_pet.css`
- `frontend/js/desktop_pet.js`
- `scripts/start_backend.py`
- 现有 FastAPI 聊天与会话 API

#### Acceptance Criteria

- 桌宠可独立启动并连接/拉起后端。
- 桌宠窗口透明、无边框、置顶、可拖拽。
- 气泡聊天完整走通：输入 → 思考 → 回复。
- 宠物问候与轻量主动关怀能触发桌面提醒气泡。
- 桌面提醒气泡只展示 2 个字左右的心情/主题概括，不直接展示完整消息内容。
- 点击气泡或宠物后能展开完整聊天面板查看消息。
- 桌面情境提醒仅使用低敏信号，不读取屏幕内容或敏感应用内容。
- 右键可以打开完整 Web 面板。
- 关闭窗口后程序进入托盘驻留。
- 桌宠和 Web 共用同一后端会话与记忆。

---

### Phase 3：桌宠体验增强 + 养成体系

#### Goal

在桌宠 MVP 验证可行后，将桌宠从“能用”升级为“适合长期挂着”的陪伴产品。

#### Deliverables

1. 桌宠基础体验增强：
   - 开机自启。
   - 窗口位置记忆。
   - 多显示器适配。
   - 勿扰模式。
   - 通知隐私设置。
2. 宠物状态动画增强：
   - idle：待机/呼吸。
   - happy：开心跳动。
   - lonely：等待陪伴。
   - sleepy：困倦/睡觉。
   - studying：陪学状态。
3. 主动提醒能力：
   - 久坐提醒。
   - 喝水提醒。
   - 睡觉提醒。
   - 学习计划提醒。
4. 学习陪伴桌宠化：
   - 和现有“陪你学 GitHub 项目”能力联动。
   - 章节完成后桌宠庆祝。
   - 学习停滞时温和提醒。
5. 多宠物切换：
   - 复用现有自定义宠物持久化能力。
   - 保持每只宠物的人格、口头禅、开场白与记忆连续性。
6. 数据目录与备份：
   - SQLite 从项目目录迁移到用户应用数据目录，例如 `%APPDATA%/QAgentPet/`。
   - 提供旧库自动复制、备份、回退路径。
   - 提供本地备份与恢复能力。

#### Main Files / Modules

- `desktop/` 全模块
- `backend/database.py`
- `backend/services/learning_service.py`
- `backend/services/memory_service.py`
- `frontend/js/desktop_pet.js`
- `frontend/css/desktop_pet.css`

#### Acceptance Criteria

- 重启电脑后桌宠可自动启动并恢复上次位置。
- 勿扰模式下不弹出主动气泡，但托盘仍驻留。
- 至少 5 种宠物状态动画可稳定切换。
- 学习陪伴模式和现有学习数据联动。
- SQLite 迁移不丢失聊天记录、亲密度、宠物配置和学习数据。
- 本地备份/恢复可验证成功。

---

### Phase 4：QQ/IM/移动端扩展

#### Goal

在 Web + 桌宠主线稳定后，将 QQ、其他 IM 或移动端作为可选入口接入统一宠物核心。

#### Deliverables

1. QQ Bot 适配器：
   - 接入统一聊天 API。
   - 保持人格、记忆、亲密度连续。
2. 移动端 H5 或小程序入口：
   - 轻量聊天。
   - 宠物状态查看。
   - 基础提醒设置。
3. 多端会话同步：
   - 同一用户下跨端同步消息、记忆、宠物状态。
   - 避免多个入口各自形成孤立人格。

#### Main Files / Modules

- 可新增 `adapters/qq_bot.py`
- 可新增 `adapters/mobile_api.py`
- 后端 session / user / memory 同步层
- 现有聊天 API 与用户画像服务

#### Acceptance Criteria

- QQ/移动端消息能触发宠物回复。
- 多端共享同一宠物人格、记忆、亲密度。
- Web、桌宠、QQ/移动端切换时上下文不割裂。

---

### Cross-Phase Dependencies

```text
Phase 0 情感捕捉细化
    │  为宠物状态系统、主动关怀和桌宠行为决策提供结构化情感信号
    ▼
Phase 1 产品定位调整 + Web 端电子宠物化
    │  先在 Web 端验证电子宠物叙事和 UI，再投入桌宠工程
    ▼
Phase 2 桌宠 MVP
    │  验证桌面常驻形态是否成立
    ▼
Phase 3 桌宠体验增强 + 养成体系
    │  在 MVP 稳定后再增强长期陪伴、提醒、备份和数据迁移
    ▼
Phase 4 QQ/IM/移动端扩展
```

依赖说明：

- Phase 0 是后续所有“宠物行为决策”的数据基础。
- Phase 1 是产品叙事和 UI 原型验证阶段，能减少 Phase 2 桌宠返工。
- Phase 2 是转型是否成立的关键里程碑。
- Phase 3 应在桌宠 MVP 证明有使用价值后再投入。
- Phase 4 不应抢占当前 Web + 桌宠主线资源。

---

### Risks and Mitigations

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 结构化输出不稳定 | 情感字段缺失，宠物行为策略退化 | 增强 few-shot 示例；解析函数提供直接 JSON、正则提取、纯文本 fallback；记录 fallback 比例 |
| 高风险安全策略误判/漏判 | 用户危机场景回应不当，或普通对话被过度干预 | `risk_level=high` 采用保守安全策略；medium 以下保持宠物人格；定期抽样复核高风险日志 |
| Electron 包体过大/内存较高 | 影响“轻量桌宠”预期 | MVP 用 Electron 验证功能；后续评估 Tauri；打包时排除无关资源 |
| 后端自动启动失败 | 桌宠无法使用 | 首次启动环境自检；端口检测；失败时给出明确修复指引；长期可考虑 PyInstaller 打包后端 |
| SQLite 迁移损坏用户数据 | 聊天记录、亲密度、学习数据丢失 | 迁移前检测旧库；先复制再切换；保留备份和回退路径；提供手动恢复说明 |
| Web 宠物化影响现有功能 | 聊天、学习、串门等核心能力回归 | 宠物状态组件作为增量叠加；核心聊天逻辑尽量不动；增加回归测试 |
| 桌宠与 Web 会话不同步 | 用户跨端体验割裂 | 共用同一 session/user/memory API；桌宠打开 Web 时传递当前会话信息 |
| 桌面情境提醒气泡过度打扰或引发隐私担忧 | 用户可能觉得被监控、被打断，或在桌面暴露完整私密消息 | MVP 只使用低敏上下文信号；气泡只展示 2 个字左右概括，不展示完整内容；默认控制频率；提供勿扰模式；不读取屏幕内容、窗口文本或敏感应用内容 |
| 过早引入 Live2D 或复杂动画 | 开发周期失控 | MVP 坚持图片 + CSS 动画；Live2D 作为后续可选资源包 |

---

### Implementation Recommendations

1. **先落地 Phase 0**：情感捕捉细化已在计划中明确，实施成本相对低，是桌宠行为和主动陪伴的数据基础。
2. **Phase 1 与 Phase 2 不要混做**：先用 Web 端统一叙事和验证宠物化 UI，再启动 Electron 桌宠，降低返工成本。
3. **后端继续作为统一 Core**：桌宠不重写后端，只作为新客户端调用现有 API。
4. **可新增桌宠专用 API 子集**：后续可考虑 `/api/desktop/`，只返回桌宠需要的聊天、状态、提醒、当前宠物信息。
5. **不要过早做 Live2D**：先用静态图 + CSS 动画验证陪伴闭环。
6. **数据迁移放到 Phase 3**：SQLite 用户数据目录迁移风险高，应在桌宠 MVP 稳定后进行。
7. **从 Phase 0 开始记录关键指标**：结构化解析成功率、fallback 比例、risk_level 触发率、桌宠气泡点击率、桌宠留存等。
