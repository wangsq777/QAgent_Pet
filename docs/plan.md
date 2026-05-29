# 口头禅概率控制

## 问题描述

宠物 Agent 口头禅触发概率为 100%。以 Hot Dog 为例，每次回复都会包含"汪汪，我好想你"这个口头禅。需要让口头禅只在部分回复中出现，而不是每次都带。

## 根因分析

口头禅通过 System Prompt 的"输出要求"以绝对指令形式注入 LLM：

```
2. 口头禅是"汪汪，我好想你。"
```

LLM 将此理解为"每次回复都必须包含口头禅"，导致触发概率 100%。代码层面没有任何控制逻辑，完全依赖 LLM 自行决定。

## 当前架构

- **滑动窗口**：最近 10 条消息（约 5 轮对话）传给 LLM 作为上下文
- **口头禅来源**：
  - Hot Dog: `"汪汪，我好想你。"` → `hot_dog.py` System Prompt 第 39 行
  - Cold Cat: `"哼。本咪才不会关心你。"` → `cold_cat.py` System Prompt 第 42 行
  - 鼠鼠: `"鼠鼠我啊......"` → `mouse.py` System Prompt 第 43 行
  - 自定义宠物: `custom_pets_storage[pet_id].catchphrase`
- **Prompt 组装**：`chat.py` 第 362-407 行构建 full_prompt

## 实现方案

采用**方案 B：代码层面检测 + Prompt 动态注入**。

### 核心思路

保持 System Prompt 中口头禅定义不变（LLM 仍知道口头禅是什么），在 `chat.py` 中新增两个辅助函数，在构建 full_prompt 时根据滑动窗口中口头禅是否已出现过，动态追加精确指令。

### 具体步骤

1. **新增 `get_catchphrase()` 函数**：根据 pet_type 和 custom_pet_id 获取对应口头禅文本
2. **新增 `detect_catchphrase_in_history()` 函数**：在最近 10 条 assistant 消息中检测口头禅是否出现过
3. **修改 full_prompt 组装逻辑**：在【重要规则】区域动态追加：
   - 口头禅在最近 10 条中出现过 → 追加 `本次回复请不要使用口头禅。`
   - 口头禅未出现 → 追加 `本次回复请使用你的口头禅。`

### 涉及文件

仅修改 `backend/routers/chat.py`，不修改任何 Prompt 文件。

### 边界情况

- **首轮对话**：无历史消息 → 判定为"未出现过"，触发"请使用口头禅"
- **自定义宠物无口头禅**：catchphrase 为空 → 跳过检测，不追加任何指令
- **口头禅变体匹配**：使用简单子串匹配，覆盖 LLM 可能的微调变体

---

## 实现记录

### 2026-05-29: 方案 B 已实现

**修改文件**：仅 `backend/routers/chat.py`

**新增函数**：
- `get_catchphrase(pet_type, custom_pet_id)`（行39-52）：返回宠物口头禅文本。内置三只宠物使用 System Prompt 中的精确口头禅，自定义宠物从 `custom_pets_storage[pet_id].catchphrase` 获取。
- `detect_catchphrase_in_history(recent_messages, catchphrase)`（行55-67）：遍历最近 10 条消息中的 assistant 消息，使用子串匹配检测口头禅是否已出现。

**修改点**：
- `recent_conversation` 构建后（行345-352）：调用 `get_catchphrase()` + `detect_catchphrase_in_history()` 生成 `catchphrase_rule` 变量。
- `【重要规则】` 区域（行446）：动态注入 `{catchphrase_rule}` —— 口头禅已出现则追加"本次回复请不要使用口头禅"，未出现则追加"本次回复请使用你的口头禅"；无口头禅时该行为空。

**边界处理验证**：
- 首轮对话（无历史）→ `detect_catchphrase_in_history` 返回 `False` → 规则 7 为"请使用口头禅" ✓
- 自定义宠物无口头禅 → `get_catchphrase` 返回 `""` → `catchphrase_rule` 为 `""` → 不追加任何指令 ✓
- 变体匹配 → 子串 `in` 匹配覆盖 LLM 微调 ✓

### 2026-05-29: 修复口头禅权威冲突问题

**问题**：方案 B 实现后，口头禅仍然每轮都出现。原因是 System Prompt 中硬编码了"口头禅是'XXX'"（身份级权威），而动态规则 7 的"请不要使用口头禅"（编号级弱指令）无法对抗。

**修复方案**：消除 System Prompt 与动态规则的权威冲突，改为单一信息源。

**修改文件**：
1. `backend/prompts/hot_dog.py` 第39行：`口头禅是"汪汪，我好想你。"` → `口头禅由系统在对话时动态告知`
2. `backend/prompts/cold_cat.py` 第42行：`口头禅是"哼。本咪才不会关心你。"` → `口头禅由系统在对话时动态告知`
3. `backend/prompts/mouse.py` 第43行：`口头禅是"鼠鼠我啊......"` → `口头禅由系统在对话时动态告知`
4. `backend/prompts/custom_pet.py` 第249-250行：`口头禅是"{catchphrase}"` → `口头禅由系统在对话时动态告知`
5. `backend/routers/chat.py` 第352行：规则 7 从 `"本次回复请使用你的口头禅"` → `"本次回复请使用口头禅：'{catchphrase}'"`（带上具体文本）

**核心改动逻辑**：
- System Prompt 不再硬编码口头禅文本，只声明"口头禅由系统在对话时动态告知"
- 口头禅的唯一信息源变为规则 7：未出现时注入具体文本 `"本次回复请使用口头禅：'汪汪，我好想你。'"`，已出现时注入 `"本次回复请不要使用口头禅。"`
- LLM 无权威冲突，服从规则 7 即可
