# QAgent Pet 需求计划

---

## ✅ 已实现：口头禅概率控制

### 问题

宠物 Agent 口头禅触发概率为 100%，每次回复都包含口头禅（如 Hot Dog 每次都说"汪汪，我好想你"），需要降低频率。

### 解决方法

采用**代码层面检测 + Prompt 动态注入**（方案 B）：

1. 在 `chat.py` 中新增 `get_catchphrase()` 和 `detect_catchphrase_in_history()` 两个函数，检测最近 10 条 assistant 消息中口头禅是否已出现
2. 消除 System Prompt 与动态规则的权威冲突——将 Prompt 文件中的 `口头禅是"XXX"` 改为 `口头禅由系统在对话时动态告知`
3. 在 full_prompt 的【重要规则】区域动态追加指令：口头禅已出现 → `本次回复请不要使用口头禅`，未出现 → `本次回复请使用口头禅：'{具体文本}'`

### 最终效果

- 口头禅不再每轮都出现，由代码精确控制频率
- 首轮对话自动触发口头禅，后续轮次间隔出现
- 覆盖 3 种预置宠物和自定义宠物

### 修改文件

- `backend/routers/chat.py`：新增辅助函数 + 动态注入逻辑
- `backend/prompts/hot_dog.py`、`cold_cat.py`、`mouse.py`、`custom_pet.py`：消除硬编码权威冲突

---

## ✅ 已实现：自定义宠物持久化存储

### 问题

用户创建自定义宠物后，退出浏览器再打开，自定义宠物消失。根因：`custom_pets_storage` 是纯内存字典，服务器重启后数据丢失。

### 解决方法

将存储从内存字典迁移到 SQLite 数据库：

1. **`database.py`**：新增 `custom_pets` 表（含 `user_id` 隔离 + 索引）
2. **`custom_pets.py`**：删除 `custom_pets_storage` 字典，5 个 API 接口全部改为 `get_db()` 数据库读写
3. **`chat.py`**：新增 `get_catchphrase_async()` 和 `get_custom_pet_info()`，从数据库查询替代内存字典
4. **`sessions.py`**：欢迎语生成改为从数据库查询

### 最终效果

- 自定义宠物数据持久化在 `qagent_pet.db`，重启/刷新不丢失
- 支持用户隔离（`user_id` 字段）
- 删除后聊天降级处理，不崩溃

---

## 📋 待实现：自定义宠物开场白 LLM 生成

### 问题

用户创建自定义宠物后，所有宠物的开场白都千篇一律。根因：`custom_pet.py` 的 `generate_welcome_messages()` 使用硬编码模板匹配，按性格标签返回固定 3 句话，完全没有 LLM 参与。例如所有"热情"标签的宠物开场白永远是 `"汪！主人！我等你好久啦！"`（狗味），无论实际是什么动物。

对比：预置宠物（Hot Dog/Cold Cat/鼠鼠）的开场白通过 `llm_service.generate_welcome_message()` 调用 LLM 根据身份和性格动态生成，每次不同且贴合角色。

### 当前架构

```python
# backend/prompts/custom_pet.py 第 359-405 行
def generate_welcome_messages(pet_name, pet_type, personality_tags, catchphrase):
    if "热情" in personality_tags or "活泼" in personality_tags:
        welcomes = ["汪！主人！我等你好久啦！", ...]  # 硬编码，全是狗味
    elif "高冷" in personality_tags or "傲娇" in personality_tags:
        welcomes = ["哼...你来了啊。", ...]           # 硬编码
    ...
```

调用链路：
- `sessions.py` 创建会话时调用 `generate_welcome_messages()` → 取 `welcomes[0]`
- `custom_pets.py` 预览时也调用同一函数

### 实现方案

1. **`backend/services/llm_service.py`**：扩展 `generate_welcome_message()` 支持自定义宠物参数
   - 新增参数：`pet_type`（动物种类）、`personality_tags`（性格标签列表）、`catchphrase`（口头禅）
   - 构建 Prompt：`"你是{pet_name}，一只{pet_type_display}，性格{tags}。请用你的风格写一句简短的欢迎主人的话（30字以内）。"`
   
2. **`backend/prompts/custom_pet.py`**：将 `generate_welcome_messages()` 改为调用 LLM
   - 保留函数签名兼容性，内部改为调用 `llm_service.generate_welcome_message()`
   - 或直接废弃该函数，让调用方直接使用 LLM 服务

3. **`backend/routers/sessions.py`**（第 121-127 行）：将 `generate_welcome_messages()` 调用替换为 LLM 生成
   
4. **`backend/routers/custom_pets.py`**（第 149-154 行）：预览接口同步改为 LLM 生成

### 边界情况

- **LLM 不可用时降级**：保留现有硬编码模板作为 fallback
- **生成失败重试**：最多重试 1 次
- **超时控制**：欢迎语生成设置较短的 max_tokens（50），避免阻塞会话创建
- **宠物类型映射**：将 `pet_type`（如 `hamster`、`fox`）映射为中文显示名传给 LLM

---

## ✅ 已实现：自定义宠物删除功能

### 问题

用户创建了自定义宠物后，在首页 `index.html` 的宠物列表中无法删除不需要的自定义宠物。当前后端虽然已有 `DELETE /api/custom-pets/detail/{pet_id}` 接口，但：
1. 前端缺少删除按钮和交互流程
2. 后端删除接口未校验用户归属（`user_id` 硬编码为 `default_user` 但未在查询中体现）
3. 删除宠物时未清理关联数据（`pet_sessions`、`messages`、`long_term_memories`、`schedules`、`memory_vectors`），会产生孤儿数据

### 当前架构

**数据库关系链（删除时需要级联清理）**：
```
custom_pets (pet_id)
  └── pet_sessions (custom_pet_id)  ← 通过 custom_pet_id 关联
        ├── messages (session_id)
        ├── long_term_memories (session_id)
        ├── schedules (session_id)
        └── memory_vectors (session_id)
```

- **注意**：数据库表定义中这些外键没有 `ON DELETE CASCADE`，需要应用层手动清理。
- 预置宠物（`hot_dog`、`cold_cat`、`mouse`）不存储在 `custom_pets` 表中，天然无法被误删。

**后端**：`backend/routers/custom_pets.py:340-356`
```python
@router.delete("/detail/{pet_id}")
async def delete_custom_pet(pet_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT pet_id FROM custom_pets WHERE pet_id = ?", (pet_id,)
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="宠物不存在")
        await db.execute("DELETE FROM custom_pets WHERE pet_id = ?", (pet_id,))
        await db.commit()
    return {"message": "删除成功"}
```
问题：
- 仅查询 `custom_pets` 表（预置宠物不在其中），不会误删预置宠物 —— 但缺少显式的 `pet_id.startswith("custom_")` 防护
- 未按 `user_id` 过滤，任何用户可删除任意自定义宠物
- 删除宠物后，关联的 sessions / messages / vectors 等成为孤儿数据

**前端**：`frontend/index.html` 的 `loadCustomPets()` 函数（178-237行）
- 为每个自定义宠物动态创建 `.pet-card.custom-pet-user` 卡片
- 卡片只有「选择」按钮，无「删除」按钮

**API 客户端**：`frontend/js/api.js`
- 有 `listCustomPets()` 和 `createCustomPet()`，无 `deleteCustomPet()`

### 实现方案

#### 后端改造（`backend/routers/custom_pets.py`）

重写 `delete_custom_pet` 函数，执行以下步骤（在一个事务中）：

1. **安全校验**：
   - 校验 `pet_id` 必须以 `custom_` 开头（防止恶意传入预置宠物名如 `hot_dog`）
   - 按 `user_id` 查询宠物，确保只能删除自己的宠物（当前 `user_id` 硬编码为 `"default_user"`，与项目现有模式保持一致）

2. **查找关联会话**：
   - 查询 `pet_sessions` 表中所有 `custom_pet_id = pet_id` 的 `session_id` 列表

3. **级联清理关联数据**（按外键依赖顺序）：
   - 删除 `messages` 表中属于这些 session 的记录
   - 删除 `long_term_memories` 表中属于这些 session 的记录
   - 删除 `schedules` 表中属于这些 session 的记录
   - 删除 `memory_vectors` 表中属于这些 session 的记录
   - 删除 `pet_sessions` 表中这些 session 的记录

4. **删除宠物记录**：
   - 删除 `custom_pets` 表中的宠物行

5. **提交事务**：`await db.commit()`

#### 前端改造

**`frontend/js/api.js`**：
- 新增 `deleteCustomPet(petId)` 函数，调用 `DELETE /api/custom-pets/detail/{petId}`

**`frontend/index.html`**：
- 在 `loadCustomPets()` 中，为每个自定义宠物卡片追加一个删除按钮（样式为红色/警告色小按钮，放在卡片底部或右上角）
- 点击删除时弹出确认对话框（`confirm('确定要删除宠物「XXX」吗？此操作不可撤销，所有聊天记录将被清除。')`）
- 确认后调用 `API.deleteCustomPet(petId)`，成功则从 DOM 中移除该卡片
- 如果删除后自定义宠物列表为空，显示空状态提示
- 删除按钮在请求期间显示 loading 状态（禁用 + 文字变为「删除中...」）

**CSS 样式**（`frontend/index.html` 内联 `<style>`）：
- `.delete-pet-btn`：红色小按钮，位于卡片右上角或选择按钮下方
- hover 时加深颜色

### 边界情况

- **预置宠物防护**：前端硬编码的 3 张预置宠物卡片没有删除按钮；后端双重校验 `pet_id.startswith("custom_")`
- **宠物不存在**：返回 404，前端提示用户
- **并发删除**：两个标签页同时删除同一宠物，第二次请求返回 404，前端静默处理或提示「宠物已被删除」
- **有关联会话但无消息**：即使该宠物从未被聊过天（无 messages），仍需清理 `pet_sessions` 表
- **删除当前正在使用的宠物**：如果用户正在 `chat.html` 中与该宠物对话，删除后回到首页再选择同一宠物会因 session 已被清除而重新创建新 session（这是预期行为）
- **网络错误**：前端 catch 错误，提示用户「删除失败，请重试」
- **空状态恢复**：删除全部自定义宠物后，需重新显示「还没有创建自定义宠物」提示（当前代码在卡片被移除后不会自动恢复，需要在删除完成后检查）

### 修改文件

- `backend/routers/custom_pets.py`：重写 `delete_custom_pet` 函数，增加安全校验 + 级联清理
- `frontend/js/api.js`：新增 `deleteCustomPet(petId)` 方法
- `frontend/index.html`：在 `loadCustomPets()` 中为每张自定义宠物卡片添加删除按钮 + 确认交互 + DOM 清理逻辑 + 空状态恢复
