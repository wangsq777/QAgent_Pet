# QAgent Pet 需求计划

---

需求：口头禅概率控制已实现。

需求：自定义宠物持久化存储已实现。

需求：自定义宠物删除功能已实现。

需求：自定义宠物开场白 LLM 生成已实现。

需求：宠物 Agent 串门通信（Phase 1 核心功能 + Phase 2 记忆沉淀）已实现。

---

## [2026-06-17] Plan for 情绪感知两层架构重构

### Requirement

将当前阻塞在响应路径中的独立 LLM 情绪识别调用（`llm_service.extract_emotion`）拆分为两层：

- **前台**：将情绪标签（`emotion`，取值 `happy/sad/anxious/tired/neutral`）内嵌进主 LLM 调用，令主 LLM 在生成宠物回复的同时以 JSON 格式同步输出结构化字段，彻底消除额外的 LLM 调用。情绪标签写入 `messages.emotion_tag`，用于亲密度计算及 `ChatResponse` 返回前端。
- **后台**：新增专职情绪后台 Agent，每隔 N 轮读取最近对话历史，输出用户的长期情绪倾向描述（如”最近持续焦虑，偶尔开心”），异步写入 `user_profiles.mood_tendency`。使用 `FastAPI BackgroundTasks` 实现零阻塞。

### Design Overview

#### 前台：主 LLM 结构化输出

当前 `full_prompt` 末尾要求 LLM”直接输出回复内容”，回复是纯文本。改造后要求 LLM 输出 JSON：

```json
{
  “reply”: “宠物的回复内容（含工具调用标记、日程标记等，与现在格式一致）”,
  “emotion”: “neutral”
}
```

**关键约束**：
1. `reply` 字段内容与当前纯文本回复格式完全一致，工具调用标记 `[TOOL_CALL]...[/TOOL_CALL]`、日程标记 `[SCHEDULE:...]` 原样保留在 `reply` 字段内，下游解析逻辑不变。
2. `emotion` 字段只能是五选一：`happy / sad / anxious / tired / neutral`。
3. `_call_llm` 不新增结构化输出模式，改为在 `chat.py` 内直接解析 JSON 文本，失败时 `emotion` 降级为 `”neutral”`，`reply` 降级为原始文本。

**Prompt 末尾改动**（`chat.py` 中 `full_prompt` 末尾两行）：

```
# 删除
请用{pet_type}的性格风格回复，直接输出回复内容。

# 替换为
请用{pet_type}的性格风格回复，并以 JSON 格式输出，格式严格如下（不要 markdown 代码块，不要多余字段）：
{{“reply”: “你的回复内容”, “emotion”: “用户情绪标签(happy/sad/anxious/tired/neutral)”}}
其中 emotion 是你对当前用户消息情绪的判断，不是宠物自己的情绪。
```

**JSON 解析辅助函数**（新增于 `chat.py`）：

```python
def parse_structured_reply(raw: str) -> tuple[str, str]:
    “””
    解析主 LLM 的结构化输出，返回 (reply_text, emotion_tag)。
    失败时返回 (raw, “neutral”)。
    “””
    import json, re
    valid_emotions = {“happy”, “sad”, “anxious”, “tired”, “neutral”}
    try:
        # 尝试直接解析
        data = json.loads(raw)
        reply = data.get(“reply”, raw)
        emotion = data.get(“emotion”, “neutral”).strip().lower()
        if emotion not in valid_emotions:
            emotion = “neutral”
        return reply, emotion
    except Exception:
        # 尝试从文本中提取 JSON 块（LLM 有时会在 JSON 前后加文字）
        match = re.search(r'\{.*?”reply”.*?”emotion”.*?\}', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                reply = data.get(“reply”, raw)
                emotion = data.get(“emotion”, “neutral”).strip().lower()
                if emotion not in valid_emotions:
                    emotion = “neutral”
                return reply, emotion
            except Exception:
                pass
        return raw, “neutral”
```

**工具调用（ReAct）路径**：`execute_tools_and_build_final_prompt` 的二次 LLM 调用（`caller=”tool_feedback”`）也需要同样的结构化输出改造。该函数的 `second_prompt` 末尾同步更新，解析逻辑复用 `parse_structured_reply`。

#### 后台：情绪 Agent（BackgroundTasks）

新增文件 `backend/services/mood_agent.py`，实现 `MoodAgent` 类：

```python
class MoodAgent:
    TRIGGER_INTERVAL = 5  # 每 5 轮对话触发一次

    async def should_trigger(self, session_id: str, total_chats: int) -> bool:
        return total_chats % self.TRIGGER_INTERVAL == 0

    async def analyze_mood_tendency(self, user_id: str, session_id: str) -> None:
        “””
        读取最近 15 条用户消息，输出情绪倾向文本，写入 user_profiles.mood_tendency。
        “””
```

**Prompt 设计**：

```
以下是用户最近的发言（按时间顺序）：
{最近 15 条 role=user 的消息内容}

请用 20 字以内描述这位用户近期的情绪倾向（如”最近持续焦虑，偶尔开心”）。
直接输出描述文字，不要任何解释。
```

**触发逻辑**（`chat.py` 的 `chat` 函数末尾）：

```python
from fastapi import BackgroundTasks

# chat 函数签名追加 background_tasks 参数
async def chat(request: Request, session_id: str, chat_req: ChatRequest, background_tasks: BackgroundTasks):
    ...
    # 在 return ChatResponse 之前注册后台任务
    if await mood_agent.should_trigger(session_id, new_total_chats):
        background_tasks.add_task(
            mood_agent.analyze_mood_tendency,
            user_id=session_dict[“user_id”],
            session_id=session_id
        )
```

#### user_profile_agent 的 mood_tendency 字段处理

`user_profile_agent.analyze_and_extract` 的 Prompt 目前包含 `mood_tendency` 字段，导致它也在每轮更新这个字段，与新的专职 Agent 产生竞争写入。

处理方案：**从 `user_profile_agent` 的 Prompt 中移除 `mood_tendency` 字段**，该字段的更新权交给 `MoodAgent` 独占。`memory_service.merge_user_profile` 的合并逻辑本身是字段级 UPSERT，两个 Agent 写不同字段不会冲突，只需从 `user_profile_agent` 的 Prompt 和 JSON schema 中删去该字段即可。

#### ChatResponse 字段

`ChatResponse.emotion_tag` 字段保留不变，来源从 `llm_service.extract_emotion` 的返回值改为 `parse_structured_reply` 的第二个返回值。前端零改动。

#### 数据流图

```
用户消息
   │
   ▼
主 LLM 调用（caller=”main_chat”）
   │  full_prompt 末尾要求 JSON 输出
   │  {reply: “...”, emotion: “sad”}
   ▼
parse_structured_reply()
   ├─ reply_text  → execute_tools_and_build_final_prompt → 最终回复
   └─ emotion_tag → calculate_intimacy_change → 亲密度计算
                  → save_message(emotion_tag=...) → messages 表
                  → ChatResponse.emotion_tag → 前端

(每 5 轮，response 返回后异步)
   ▼
MoodAgent.analyze_mood_tendency()
   │  读取最近 15 条用户消息
   │  轻量 LLM 调用（caller=”mood_agent”）
   └─ 写入 user_profiles.mood_tendency
```

### Implementation Tasks

1. **`backend/routers/chat.py`（核心改造）**
   1. 新增辅助函数 `parse_structured_reply(raw: str) -> tuple[str, str]`（含 JSON 解析 + 正则兜底）
   2. 修改 `full_prompt` 末尾指令：将”直接输出回复内容”替换为 JSON 格式要求
   3. 修改主 LLM 调用后的处理逻辑：
      - `raw_reply = await llm_service.chat(..., caller=”main_chat”)`
      - `reply, emotion_tag = parse_structured_reply(raw_reply or fallback_text)`（注意 fallback 分支）
   4. 删除 `emotion_tag = await llm_service.extract_emotion(...)` 这一行（第 565 行）
   5. 修改 `execute_tools_and_build_final_prompt`：
      - `second_prompt` 末尾同步改为 JSON 格式要求
      - 函数返回值从 `(str, dict)` 改为 `(str, str, dict)`，增加 `emotion_tag` 返回
      - 或在调用处对二次 LLM 结果再次调用 `parse_structured_reply`（推荐，避免修改函数签名）
   6. 在函数签名加入 `background_tasks: BackgroundTasks`，并在 `return ChatResponse` 前注册后台任务
   7. 在文件顶部 import `BackgroundTasks` 和 `mood_agent`

2. **新增 `backend/services/mood_agent.py`**
   - 实现 `MoodAgent` 类，含 `should_trigger` 和 `analyze_mood_tendency` 方法
   - `analyze_mood_tendency` 内：读取 session 最近 15 条 `role=user` 消息 → 构建 Prompt → 调用轻量 LLM → 写入 `user_profiles.mood_tendency`（通过 `memory_service.merge_user_profile`）
   - 导出全局单例 `mood_agent`

3. **`backend/services/user_profile_agent.py`**
   - 从 `PROFILE_EXTRACT_PROMPT` 的说明列表中删除第 7 条”情绪倾向”
   - 从 JSON schema 示例中删除 `”mood_tendency”` 字段
   - 从 `has_data` 检查逻辑中无需改动（字段消失后自然不会产生该字段的值）

4. **`backend/services/llm_service.py`**
   - `extract_emotion` 方法可保留（供其他潜在调用方使用），但在 `chat.py` 中不再调用它
   - 无需新增结构化输出模式，`_call_llm` 不变

5. **`backend/schemas.py`**
   - `ChatResponse` 不变（`emotion_tag: str` 字段保留）

6. **`docs/update.md`**
   - 按项目规范记录本次更新内容

### Risks and Mitigations

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 主 LLM 不遵循 JSON 格式，返回纯文本 | emotion 降级为 neutral，reply 内容仍可正常展示 | `parse_structured_reply` 的双重兜底（直接解析 + 正则提取）已覆盖大多数情况 |
| 主 LLM 将 reply 字段内容截断或编码 JSON 特殊字符 | 回复内容缺失或乱码 | 解析失败时直接用 `raw` 原文作为 reply，不丢弃用户体验 |
| 工具调用路径（ReAct）的二次 LLM 也改了格式 | 工具结果回复丢失 | `execute_tools_and_build_final_prompt` 的 `second_prompt` 同步改造，复用 `parse_structured_reply`，emotion 忽略（工具轮次不更新 emotion） |
| `mood_agent` 写入 `mood_tendency` 与 `user_profile_agent` 竞争 | 字段互相覆盖 | 从 `user_profile_agent` Prompt 中删除该字段，`merge_user_profile` 的 field-level 合并逻辑天然隔离 |
| 后台 mood_agent 调用 LLM 失败 | 不影响响应；该轮 `mood_tendency` 不更新 | `analyze_mood_tendency` 内 try/except 全局兜底，失败只记日志 |
| 每隔 5 轮的触发条件基于 `new_total_chats` 的模运算，多 session 场景下可能同时触发多个后台任务 | LLM 并发消耗增加 | 轻量模型 + 每任务独立超时，可接受；后续可加分布式限流 |

### Testing Strategy

- **单元测试 `parse_structured_reply`**：
  - 输入合法 JSON：断言 reply 和 emotion 正确提取
  - 输入 JSON 前后带冗余文字：断言正则提取仍成功
  - 输入纯文本（LLM 拒绝 JSON 格式）：断言返回 `(raw, “neutral”)`
  - 输入 emotion 为非法值（如 `”angry”`）：断言 emotion 降级为 `”neutral”`
- **集成测试（chat 端点）**：
  - Mock `llm_service.chat` 返回合法 JSON → 断言 `ChatResponse.emotion_tag` 非 neutral（如 `sad`）
  - Mock `llm_service.chat` 返回纯文本 → 断言请求仍成功，`emotion_tag == “neutral”`
  - 验证 `llm_service.extract_emotion` 不再被调用（Mock 断言 call_count == 0）
- **后台任务测试**：
  - 触发第 5 轮对话后检查 `user_profiles.mood_tendency` 是否被写入
  - Mock `mood_agent.analyze_mood_tendency` 抛异常 → 断言 `ChatResponse` 仍正常返回
- **回归测试**：
  - 日程标记 `[SCHEDULE:...]` 在 reply 字段内仍被正确解析提取
  - 工具调用标记 `[TOOL_CALL]...[/TOOL_CALL]` 在 reply 字段内仍被正确执行
  - 亲密度计算：`emotion_tag == “sad”` 时 `intimacy_change == 3`，其余为 1

---

已实现需求：宠物陪你学 GitHub 开源项目教学功能。
