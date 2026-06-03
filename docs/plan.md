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
