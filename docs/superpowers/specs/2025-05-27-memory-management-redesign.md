# QAgent Pet 记忆管理系统重构设计

## 背景

当前记忆管理系统存在以下问题：

1. 短期记忆固定取 40 条消息全量注入，无语义筛选，token 浪费严重
2. 长期记忆压缩按固定轮数（每 20 轮）触发，可能压缩掉关键对话
3. 无向量检索能力，无法做语义相似度匹配
4. 用户画像仅 4 个字段，信息维度不足
5. 所有记忆层每次全量注入 prompt，无相关性过滤

## 设计目标

1. 引入向量检索，实现语义级别的记忆召回
2. 短期记忆 token 降低约 50%，同时提升记忆质量
3. 长期记忆压缩改为话题感知，更智能地保留重要信息
4. 用户画像扩展到 8 个字段

## 约束

- 服务器环境：1-2GB RAM 轻量云服务器
- Embedding：使用云端 API（OpenAI / 智谱等），不做本地部署
- 数据库：保持 SQLite，不引入额外数据库
- 新增依赖：仅 `numpy`（用于余弦相似度计算）

---

## 一、整体架构

```
┌─────────────────────────────────────────────────┐
│                  Prompt 组装层                    │
│  (从下三层按需筛选、排序、组装最终上下文)           │
├──────────┬──────────┬──────────┬─────────────────┤
│ 短期记忆  │ 长期记忆  │ 用户画像  │  向量索引层      │
│ (滑动窗口)│ (压缩摘要)│ (结构化)  │ (Embedding+检索)│
├──────────┴──────────┴──────────┴─────────────────┤
│              SQLite 持久化存储                     │
└─────────────────────────────────────────────────┘
```

向量索引层是新增核心，不替代任何现有层，为三层记忆提供统一的语义检索能力。每条消息和每条长期记忆都生成 embedding 向量存入 SQLite。

---

## 二、向量索引层

### 2.1 新增数据库表

```sql
CREATE TABLE memory_vectors (
    vector_id    TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    source_type  TEXT NOT NULL,   -- 'message' | 'long_term'
    source_id    TEXT NOT NULL,   -- 对应 messages.message_id 或 long_term_memories.memory_id
    content      TEXT NOT NULL,   -- 原始文本（用于展示和去重）
    embedding    BLOB NOT NULL,   -- JSON 序列化的 float 数组
    importance   REAL DEFAULT 0.5, -- 重要性分数 0-1
    created_at   DATETIME NOT NULL,
    FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
);

CREATE INDEX idx_vectors_session ON memory_vectors(session_id);
```

### 2.2 新增服务 EmbeddingService

职责：
- `embed(text) -> List[float]` — 调用云端 Embedding API 获取单条文本向量
- `embed_batch(texts) -> List[List[float]]` — 批量向量化（如支持）
- `search(query_vector, session_id, top_k) -> List[MemoryItem]` — 向量相似度检索

### 2.3 向量检索算法

使用纯 Python + numpy 完成，不依赖外部向量数据库：

1. 从 `memory_vectors` 表取出该 session 的所有向量（BLOB，反序列化为 float 数组）
2. 用 numpy 计算用户消息向量与所有存储向量的余弦相似度
3. 按相似度排序，取 top-K
4. 过滤掉已在滑动窗口中的重复消息

单用户场景下（几百到几千条向量），计算耗时在毫秒级。不需要 sqlite-vec 扩展，适合 Render 等不方便装 C 扩展的环境。

---

## 三、短期记忆改造

### 3.1 双通道机制

```
每次构建上下文时：
通道 A：滑动窗口（最近 10 条）← 保证对话连贯性
通道 B：向量检索 top-5 相关历史 ← 保证记忆相关性
合并去重 → 按时间排序 → 注入 prompt
```

### 3.2 参数对比

| 参数 | 当前值 | 新值 |
|---|---|---|
| 滑动窗口大小 | 40 条 | 10 条 |
| 语义检索数量 | 无 | top-5 |
| 合并后上限 | 40 条 | 15 条 |

### 3.3 去重规则

如果某条消息既在滑动窗口中、又被向量检索召回，只保留一份。滑动窗口优先（版本更新）。

### 3.4 时间衰减加权

向量检索结果按 `相似度 × 时间衰减因子` 排序，让较新的相关记忆排在前面。

---

## 四、长期记忆改造

### 4.1 压缩触发策略（满足任一即触发）

| 触发条件 | 说明 |
|---|---|
| 滑动窗口外消息 > 30 条 | 防止未压缩的消息积压 |
| 话题变化检测 | 用 LLM 判断最近几轮是否已切换话题 |
| 消息总数 % 20 == 0 | 兜底机制（保留现有逻辑） |

### 4.2 话题变化检测

每次用户发消息时，调用 LLM 做轻量判断：

```
Prompt：
最近3轮对话：
  主人: 今天北京好热啊
  Hot Dog: 汪汪！确实很热呢，主人要注意防暑哦！
  主人: 我明天想去游泳

当前消息：对了，我之前说的那本书你记得吗？

问题：当前消息是否和最近对话是同一话题？
只回答 YES 或 NO。
```

- max_tokens=10，输入约 100 token，额外延迟约 0.5s
- 不使用 embedding 粗筛（因为 embedding 也是 API 调用，无法节省成本）
- LLM 回复 NO → 检测到话题变化 → 触发旧话题压缩

### 4.3 压缩粒度

- 每次压缩取 10-15 条消息（当前为 20 条）
- 压缩时要求 LLM 输出结构化字段：`{summary: "...", tags: ["weather", "sad"], importance: 0.8}`
- importance 由 LLM 判断（0-1），用于后续选择性注入

### 4.4 选择性注入

长期记忆不再全量注入，改为向量检索 top-3：

| | 当前方案 | 新方案 |
|---|---|---|
| 触发条件 | 固定每 20 轮 | 话题变化 / 积压>30 / 兜底20轮 |
| 压缩粒度 | 20条→1摘要 | 10-15条→1摘要+标签+重要性 |
| 注入方式 | 全部注入 | 向量检索 top-3 |

---

## 五、用户画像扩展

### 5.1 新增字段

| 字段 | 说明 | 示例 |
|---|---|---|
| `region` | 地区/城市 | 北京（保留） |
| `identity` | 身份标签 | 大学生（保留） |
| `interests` | 兴趣爱好 | 编程、篮球（保留） |
| `extra_info` | 其他信息 | 养了一只猫（保留） |
| `occupation` | 职业/专业 | 计算机科学（新增） |
| `personality_hint` | 用户性格特征 | 内向、幽默（新增） |
| `active_hours` | 活跃时段 | 22:00-01:00（新增） |
| `mood_tendency` | 情绪倾向 | 容易焦虑（新增） |

### 5.2 数据库表变更

```sql
ALTER TABLE user_profiles ADD COLUMN occupation TEXT;
ALTER TABLE user_profiles ADD COLUMN personality_hint TEXT;
ALTER TABLE user_profiles ADD COLUMN active_hours TEXT;
ALTER TABLE user_profiles ADD COLUMN mood_tendency TEXT;
```

### 5.3 提取与更新

- UserProfileAgent 的 prompt 扩展为提取 8 个字段
- merge_user_profile 逻辑不变：只更新非空新值，保留已有值
- 用户画像不做 embedding 向量化（数据量小，每次全量注入，无需检索）

---

## 六、Prompt 组装层改造

### 6.1 新 Prompt 结构

```
<system>                    ← 宠物性格 prompt（不变）
<long_term_memory>          ← 向量检索 top-3（替代全量注入）
<user_profile>              ← 8 字段画像（全量注入）
<intimacy>                  ← 亲密度 + 聊天轮数（不变）
<skills>                    ← 时间 + 工具（不变）
<recent_conversation>       ← 滑动窗口 10 条（新增，替代原<conversation>）
<related_memories>          ← 向量检索 top-5 历史消息（新增）
<current_message>           ← 用户当前消息
```

### 6.2 Token 预估对比

| 模块 | 当前方案 | 新方案 |
|---|---|---|
| 对话历史 | ~4000 token (40条) | ~1500 token (10+5条) |
| 长期记忆 | ~500 token (全量) | ~200 token (top-3) |
| 总计 | ~5500 token | ~2700 token |

节省约 50% 的 prompt token，同时记忆质量更高。

---

## 七、数据流

### 7.1 写入流程（每条消息）

```
用户消息进入
  ├→ save_message() 存入 messages 表
  ├→ embed() 生成向量 → 存入 memory_vectors 表
  └→ 返回响应

LLM 回复
  ├→ save_message() 存入 messages 表
  ├→ embed() 生成向量 → 存入 memory_vectors 表
  ├→ extract_emotion() 更新亲密度
  ├→ user_profile_agent 提取画像（异步）
  └→ 检查压缩条件
```

### 7.2 读取流程（构建上下文）

```
build_context()
  ├→ 滑动窗口：get_short_term_messages(limit=10)
  ├→ 向量检索：embedding_service.search(user_msg, top_k=5)
  ├→ 合并去重，按时间排序
  ├→ 长期记忆：embedding_service.search(user_msg, top_k=3, source_type='long_term')
  ├→ 用户画像：get_user_profile() 全量
  └→ 组装 prompt
```

---

## 八、新增依赖

```
numpy>=1.24.0    # 余弦相似度计算（约 15MB，内存占用极小）
```

Embedding API 使用现有的 `httpx` 库调用，复用项目已有的 LLM API 配置（`LLM_BASE_URL`、`LLM_API_KEY`），或新增 `EMBEDDING_API_URL` 和 `EMBEDDING_API_KEY` 配置项。

---

## 九、实施影响

### 需要修改的文件

| 文件 | 变更 |
|---|---|
| `backend/database.py` | 新增 `memory_vectors` 表，`user_profiles` 表加字段 |
| `backend/services/embedding_service.py` | **新建**，向量化与检索服务 |
| `backend/services/memory_service.py` | 改造短期/长期记忆读写逻辑 |
| `backend/services/user_profile_agent.py` | 扩展 prompt 为 8 字段提取 |
| `backend/routers/chat.py` | 改造 `build_context()`，加入向量检索 |
| `backend/config.py` | 新增 Embedding API 配置项 |
| `requirements.txt` | 新增 `numpy` |

### 不需要修改的文件

- 前端代码（纯 UI，记忆逻辑在后端）
- 宠物 prompt 文件（性格定义不变）
- 路由结构（API 接口不变）
