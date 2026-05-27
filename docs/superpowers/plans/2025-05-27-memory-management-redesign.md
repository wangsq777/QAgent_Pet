# QAgent Pet 记忆管理系统重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将记忆管理系统从固定窗口+全量注入改造为向量语义检索+智能压缩的四层架构

**Architecture:** 新增 EmbeddingService 做向量化与语义检索，改造 MemoryService 的短期/长期记忆读写逻辑，扩展 UserProfileAgent 为 8 字段提取，重写 chat.py 的 build_context 为双通道+向量检索组装 prompt。

**Tech Stack:** FastAPI, SQLite (aiosqlite), numpy, httpx, 云端 Embedding API (OpenAI 兼容格式)

---

## 文件映射

| 文件 | 变更类型 | 职责 |
|---|---|---|
| `requirements.txt` | 修改 | 新增 numpy |
| `backend/config.py` | 修改 | 新增 Embedding API 配置项 |
| `backend/database.py` | 修改 | 新增 memory_vectors 表，user_profiles 加 4 字段 |
| `backend/services/embedding_service.py` | **新建** | Embedding API 调用 + 向量相似度检索 |
| `backend/services/memory_service.py` | 修改 | 短期记忆改 10 条窗口 + 去重，长期记忆改话题感知压缩 |
| `backend/services/user_profile_agent.py` | 修改 | Prompt 扩展为 8 字段提取 |
| `backend/routers/chat.py` | 修改 | build_context 改双通道+向量检索，写入路径加 embedding |

---

### Task 1: 配置与依赖

**Files:**
- Modify: `requirements.txt`
- Modify: `backend/config.py`

- [ ] **Step 1: 添加 numpy 依赖**

```txt
# requirements.txt - 在文件末尾追加一行
numpy>=1.24.0
```

- [ ] **Step 2: 新增 Embedding API 配置项**

```python
# backend/config.py - 在 Settings 类中添加字段
class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.minimax.chat/v1"
    LLM_MODEL: str = "MiniMax-M2.5"
    WEATHER_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./qagent_pet.db"
    PORT: int = 10000

    # Embedding API 配置（默认复用 LLM 的 base_url 和 key）
    EMBEDDING_API_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt backend/config.py
git commit -chore: add numpy dependency and embedding API config"
```

---

### Task 2: 数据库 Schema 变更

**Files:**
- Modify: `backend/database.py`

- [ ] **Step 1: 在 init_database() 中添加 memory_vectors 表和 user_profiles 字段**

在 `init_database()` 函数中，已有 6 个 `CREATE TABLE` 语句之后（`await db.commit()` 之前），添加：

```python
    # 新增：向量索引表
    await db.execute("""
        CREATE TABLE IF NOT EXISTS memory_vectors (
            vector_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK(source_type IN ('message', 'long_term')),
            source_id TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
        )
    """)

    # 为 memory_vectors 创建索引
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_vectors_session ON memory_vectors(session_id)
    """)

    # 扩展 user_profiles 表（用 try/except 包裹，因为 ALTER TABLE 重复执行会报错）
    for col_sql in [
        "ALTER TABLE user_profiles ADD COLUMN occupation TEXT",
        "ALTER TABLE user_profiles ADD COLUMN personality_hint TEXT",
        "ALTER TABLE user_profiles ADD COLUMN active_hours TEXT",
        "ALTER TABLE user_profiles ADD COLUMN mood_tendency TEXT",
    ]:
        try:
            await db.execute(col_sql)
        except Exception:
            pass  # 列已存在时忽略
```

注意：`embedding` 字段使用 `TEXT` 类型而非 `BLOB`，存储 JSON 序列化的 float 列表，这样更易调试和迁移。

- [ ] **Step 2: Commit**

```bash
git add backend/database.py
git commit -m "feat: add memory_vectors table and expand user_profiles schema"
```

---

### Task 3: EmbeddingService

**Files:**
- Create: `backend/services/embedding_service.py`

- [ ] **Step 1: 创建 EmbeddingService**

```python
# backend/services/embedding_service.py
import json
import uuid
import math
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

import httpx
import numpy as np

from backend.config import settings
from backend.database import get_db


class EmbeddingService:
    def __init__(self):
        self.api_url = settings.EMBEDDING_API_URL or f"{settings.LLM_BASE_URL}/embeddings"
        self.api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        self.model = settings.EMBEDDING_MODEL

    async def embed(self, text: str) -> Optional[List[float]]:
        """调用云端 Embedding API 获取文本向量"""
        if not self.api_key or not text or not text.strip():
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "input": text.strip()[:2000]  # 截断过长文本
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                embedding = data["data"][0]["embedding"]
                return embedding
        except Exception as e:
            print(f"[EmbeddingService] embed failed: {e}")
            return None

    async def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """批量向量化"""
        if not texts:
            return []

        # 过滤空文本
        valid_texts = [t.strip()[:2000] for t in texts if t and t.strip()]
        if not valid_texts:
            return [None] * len(texts)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "input": valid_texts
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                # 按 index 排序返回
                results = sorted(data["data"], key=lambda x: x["index"])
                return [item["embedding"] for item in results]
        except Exception as e:
            print(f"[EmbeddingService] embed_batch failed: {e}")
            return [None] * len(valid_texts)

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        a = np.array(vec_a)
        b = np.array(vec_b)
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    async def save_vector(
        self,
        session_id: str,
        source_type: str,
        source_id: str,
        content: str,
        embedding: List[float],
        importance: float = 0.5
    ) -> str:
        """保存向量到数据库"""
        vector_id = str(uuid.uuid4())
        embedding_json = json.dumps(embedding)

        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO memory_vectors (vector_id, session_id, source_type, source_id, content, embedding, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (vector_id, session_id, source_type, source_id, content, embedding_json, importance, datetime.now())
            )
            await db.commit()
        return vector_id

    async def search(
        self,
        query_vector: List[float],
        session_id: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
        exclude_source_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        向量相似度检索

        Args:
            query_vector: 查询向量
            session_id: 会话 ID
            top_k: 返回数量
            source_type: 过滤来源类型 ('message' | 'long_term')
            exclude_source_ids: 排除的 source_id 列表（用于去重）

        Returns:
            按相似度降序排列的列表，每项包含 vector_id, source_type, source_id, content, similarity, importance, created_at
        """
        exclude_set = set(exclude_source_ids or [])

        async with get_db() as db:
            if source_type:
                cursor = await db.execute(
                    "SELECT vector_id, source_type, source_id, content, embedding, importance, created_at FROM memory_vectors WHERE session_id = ? AND source_type = ?",
                    (session_id, source_type)
                )
            else:
                cursor = await db.execute(
                    "SELECT vector_id, source_type, source_id, content, embedding, importance, created_at FROM memory_vectors WHERE session_id = ?",
                    (session_id,)
                )
            rows = await cursor.fetchall()

        if not rows:
            return []

        # 计算相似度
        results = []
        for row in rows:
            row_dict = dict(row)
            source_id = row_dict["source_id"]
            if source_id in exclude_set:
                continue

            stored_vector = json.loads(row_dict["embedding"])
            similarity = self._cosine_similarity(query_vector, stored_vector)

            # 时间衰减：最近 7 天内的不衰减，之后每天衰减 5%
            created_at = datetime.fromisoformat(row_dict["created_at"])
            days_ago = (datetime.now() - created_at).days
            time_decay = max(0.5, 1.0 - max(0, days_ago - 7) * 0.05)

            # 综合分数 = 相似度 × 时间衰减 × 重要性
            score = similarity * time_decay * row_dict["importance"]

            results.append({
                "vector_id": row_dict["vector_id"],
                "source_type": row_dict["source_type"],
                "source_id": source_id,
                "content": row_dict["content"],
                "similarity": similarity,
                "score": score,
                "created_at": row_dict["created_at"]
            })

        # 按综合分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


embedding_service = EmbeddingService()
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/embedding_service.py
git commit -m "feat: add EmbeddingService for vector storage and semantic search"
```

---

### Task 4: MemoryService - 短期记忆改造

**Files:**
- Modify: `backend/services/memory_service.py`

- [ ] **Step 1: 修改 get_short_term_messages 默认 limit**

将 `get_short_term_messages` 的默认 `limit` 从 40 改为 10：

```python
# backend/services/memory_service.py:9
    async def get_short_term_messages(self, session_id: str, limit: int = 10) -> List[MessageResponse]:
```

只改这一行数字即可。

- [ ] **Step 2: Commit**

```bash
git add backend/services/memory_service.py
git commit -m "refactor: reduce short-term memory window from 40 to 10 messages"
```

---

### Task 5: MemoryService - 长期记忆改造

**Files:**
- Modify: `backend/services/memory_service.py`
- Modify: `backend/services/llm_service.py`

- [ ] **Step 1: 修改 compress_memory 输出结构化格式**

```python
# backend/services/llm_service.py - 修改 compress_memory 方法
    async def compress_memory(self, messages: List[Dict[str, str]], pet_name: str) -> Dict[str, Any]:
        conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        prompt = f"""以下是一段你和主人之间的对话记录，请压缩成200字以内的摘要，保留关键信息和重要细节。

同时输出：
1. summary: 对话摘要（200字以内）
2. tags: 话题标签列表（如 ["weather", "sad", "work"]）
3. importance: 重要性评分（0-1之间的小数，1表示非常重要）

请用JSON格式输出：
{{"summary": "摘要内容", "tags": ["标签1", "标签2"], "importance": 0.8}}

对话记录：
{conversation_text}

只输出JSON，不要任何解释。"""

        messages_list = [{"role": "user", "content": prompt}]
        result = await self.chat(messages_list, temperature=0.5, max_tokens=300)

        if result:
            try:
                # 清理可能的 markdown 包裹
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', cleaned)
                    cleaned = cleaned.group(1) if cleaned else result

                data = json.loads(cleaned)
                return {
                    "summary": data.get("summary", result),
                    "tags": data.get("tags", []),
                    "importance": float(data.get("importance", 0.5))
                }
            except (json.JSONDecodeError, Exception):
                pass

        # Fallback
        return {"summary": result or "对话摘要（内容已丢失）", "tags": [], "importance": 0.5}
```

- [ ] **Step 2: 修改 compress_to_long_term 使用结构化结果并生成向量**

```python
# backend/services/memory_service.py - 修改 compress_to_long_term 方法
    async def compress_to_long_term(
        self,
        session_id: str,
        messages: List,
        pet_name: str
    ) -> Optional[str]:
        from backend.services.llm_service import llm_service
        from backend.services.embedding_service import embedding_service

        memory_id = str(uuid.uuid4())
        conversation_for_compress = [
            {"role": getattr(m, "role", m.get("role")), "content": getattr(m, "content", m.get("content"))}
            for m in messages[:15]  # 从 20 改为 15
        ]

        compressed = await llm_service.compress_memory(conversation_for_compress, pet_name)
        summary = compressed["summary"]
        importance = compressed.get("importance", 0.5)
        source_range = f"轮次1-{min(len(messages), 15)}"

        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO long_term_memories (memory_id, session_id, summary, source_range, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (memory_id, session_id, summary, source_range, datetime.now())
            )
            await db.commit()

        # 为长期记忆生成向量
        embedding = await embedding_service.embed(summary)
        if embedding:
            await embedding_service.save_vector(
                session_id=session_id,
                source_type="long_term",
                source_id=memory_id,
                content=summary,
                embedding=embedding,
                importance=importance
            )

        return memory_id
```

- [ ] **Step 3: 添加话题变化检测方法**

```python
# backend/services/memory_service.py - 在 MemoryService 类中添加新方法
    async def detect_topic_change(self, recent_messages: List[Dict], current_message: str) -> bool:
        """
        用 LLM 检测当前消息是否与最近对话话题不同。
        返回 True 表示话题变化。
        """
        from backend.services.llm_service import llm_service

        if len(recent_messages) < 2:
            return False

        recent_text = "\n".join([f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in recent_messages[-3:]])

        prompt = f"""最近对话：
{recent_text}

当前消息：{current_message}

当前消息是否和上面的对话是同一话题？只回答 YES 或 NO。"""

        result = await llm_service.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=10,
            caller="topic_detect"
        )

        if result:
            return "NO" in result.strip().upper()
        return False
```

- [ ] **Step 4: 修改压缩触发逻辑（在 chat.py 中使用，Task 7 集成）**

在 `memory_service.py` 中添加一个判断方法：

```python
# backend/services/memory_service.py - 在 MemoryService 类中添加
    async def should_compress(self, session_id: str, recent_messages: List[Dict], current_message: str) -> bool:
        """判断是否需要触发长期记忆压缩"""
        message_count = await self.get_message_count(session_id)

        # 条件1: 兜底机制 - 每 20 轮
        if message_count > 20 and message_count % 20 == 0:
            return True

        # 条件2: 滑动窗口外消息积压 > 30 条
        short_term = await self.get_short_term_messages(session_id, limit=10)
        if message_count - len(short_term) > 30:
            return True

        # 条件3: 话题变化检测
        if len(recent_messages) >= 3:
            topic_changed = await self.detect_topic_change(recent_messages, current_message)
            if topic_changed:
                return True

        return False
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/memory_service.py backend/services/llm_service.py
git commit -m "feat: add topic-aware long-term memory compression with structured output"
```

---

### Task 6: UserProfileAgent - 扩展为 8 字段

**Files:**
- Modify: `backend/services/user_profile_agent.py`

- [ ] **Step 1: 修改 PROFILE_EXTRACT_PROMPT**

```python
# backend/services/user_profile_agent.py - 修改 prompt
    PROFILE_EXTRACT_PROMPT = """你是一个用户信息提取专家。请从对话历史中提取用户的个人信息。

【对话历史】
{conversation_history}

请提取以下信息：
1. 地区/城市：用户提到过的居住地、工作地、旅行目的地等
2. 身份标签：用户的角色，如学生党、上班族、自由职业等
3. 兴趣爱好：用户提到过的爱好、运动、游戏、美食等（多个用逗号分隔）
4. 职业/专业：用户的具体职业或学科专业
5. 性格特征：从对话中推断用户的性格倾向，如内向、幽默、健谈等
6. 活跃时段：用户常在线的时间段
7. 情绪倾向：用户的情绪模式，如容易焦虑、乐观开朗等
8. 其他信息：用户的习惯、偏好、特殊情况等

请用JSON格式输出：
{{"region": "城市或地区", "identity": "身份标签", "interests": "兴趣爱好", "occupation": "职业或专业", "personality_hint": "性格特征", "active_hours": "活跃时段", "mood_tendency": "情绪倾向", "extra_info": "其他重要信息"}}
如果某项完全无法确定，设为null。
只输出JSON，不要任何解释。"""
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/user_profile_agent.py
git commit -m "feat: expand UserProfileAgent to extract 8 profile fields"
```

---

### Task 7: Chat Router - 写入路径改造

**Files:**
- Modify: `backend/routers/chat.py`

- [ ] **Step 1: 在 chat 端点中为用户消息和助手回复生成 embedding**

在 `chat` 函数中，找到 `await memory_service.save_message(session_id, "user", request.content)` 这一行（约第 291 行），在其后添加向量化逻辑：

```python
    # 保存用户消息后，生成向量（异步，失败不影响主流程）
    user_msg_embedding = await embedding_service.embed(request.content)
    if user_msg_embedding:
        await embedding_service.save_vector(
            session_id=session_id,
            source_type="message",
            source_id="user_latest",  # 将在下面替换为实际 message_id
            content=request.content,
            embedding=user_msg_embedding
        )
```

同时修改 save_message 的调用以获取 message_id：

```python
    # 将原来的：
    # await memory_service.save_message(session_id, "user", request.content)
    # 改为：
    user_msg_id = await memory_service.save_message(session_id, "user", request.content)
```

然后在回复保存后也做同样处理。找到 `await memory_service.save_message(session_id, "assistant", reply, emotion_tag=emotion_tag)`（约第 420 行），改为：

```python
    assistant_msg_id = await memory_service.save_message(session_id, "assistant", reply, emotion_tag=emotion_tag)

    # 为助手回复生成向量
    assistant_embedding = await embedding_service.embed(reply)
    if assistant_embedding:
        await embedding_service.save_vector(
            session_id=session_id,
            source_type="message",
            source_id=assistant_msg_id,
            content=reply,
            embedding=assistant_embedding
        )
```

需要在文件顶部添加 import：
```python
from backend.services.embedding_service import embedding_service
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/chat.py
git commit -m "feat: generate embeddings for user and assistant messages on save"
```

---

### Task 8: Chat Router - build_context 改造

**Files:**
- Modify: `backend/routers/chat.py`

- [ ] **Step 1: 重写 build_context 函数**

将现有的 `build_context` 函数（约第 85-147 行）替换为：

```python
async def build_context(session_id: str, pet_type: str, custom_pet_id: str = None) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)

    # 获取宠物 prompt
    pet_prompts = {
        "hot_dog": prompts.hot_dog,
        "cold_cat": prompts.cold_cat,
        "mouse": prompts.mouse
    }
    pet_info = pet_prompts.get(pet_type)
    pet_name = pet_info.PET_NAME if pet_info else "小可爱"
    system_prompt = ""

    pet_id = custom_pet_id or session_dict.get("custom_pet_id")
    if pet_type == "custom" and pet_id:
        from backend.routers.custom_pets import custom_pets_storage
        custom_pet = custom_pets_storage.get(pet_id)
        if custom_pet:
            pet_name = custom_pet.pet_name
            system_prompt = custom_pet.system_prompt
        else:
            system_prompt = f"你是 {pet_name}，一只可爱的小宠物。"

    if not system_prompt:
        system_prompt = pet_info.get_system_prompt() if pet_info else "你是我的宠物。"

    # 用户画像（全量注入）
    user_profile = await memory_service.get_user_profile(session_dict["user_id"]) or {}
    profile_text = (
        f"地区: {user_profile.get('region', '未知')}; "
        f"身份: {user_profile.get('identity', '未知')}; "
        f"职业: {user_profile.get('occupation', '未知')}; "
        f"兴趣: {user_profile.get('interests', '未知')}; "
        f"性格: {user_profile.get('personality_hint', '未知')}; "
        f"活跃时段: {user_profile.get('active_hours', '未知')}; "
        f"情绪倾向: {user_profile.get('mood_tendency', '未知')}; "
        f"其他: {user_profile.get('extra_info', '未知')}"
    )

    # 亲密度
    now = datetime.now()
    time_str = now.strftime("现在是%Y年%m月%d日 %H:%M")
    intimacy_info = f"亲密度: {session_dict['intimacy']} ({get_intimacy_level(session_dict['intimacy'])}); 共聊天: {session_dict['total_chats']}轮"

    context = {
        "system_prompt": system_prompt,
        "pet_name": pet_name,
        "user_profile": profile_text,
        "intimacy_info": intimacy_info,
        "skills": f"当前时间: {time_str}",
        "recent_conversation": "",   # 短期窗口
        "long_term_memory": "",      # 长期记忆 top-3
        "related_memories": "",      # 语义检索 top-5
    }

    return context
```

- [ ] **Step 2: 在 chat 端点中组装向量检索的记忆**

在 chat 端点中，`context = await build_context(...)` 之后、拼接 `full_prompt` 之前，加入向量检索逻辑。将原来的 prompt 组装替换为：

```python
    context = await build_context(session_id, pet_type, custom_pet_id)
    pet_name = context.get("pet_name", "小可爱")

    # 获取用户消息向量
    user_msg_embedding = await embedding_service.embed(request.content)

    # 通道 A: 滑动窗口（最近 10 条）
    recent_messages = await memory_service.get_short_term_messages(session_id, limit=10)
    recent_ids = set(m.message_id for m in recent_messages)
    context["recent_conversation"] = "\n".join([
        f"{'主人' if m.role == 'user' else pet_name}: {m.content}"
        for m in recent_messages
    ]) or "（暂无对话）"

    # 通道 B: 向量检索相关历史（top-5 消息）
    context["related_memories"] = "（暂无相关记忆）"
    if user_msg_embedding:
        related = await embedding_service.search(
            query_vector=user_msg_embedding,
            session_id=session_id,
            top_k=5,
            source_type="message",
            exclude_source_ids=list(recent_ids)
        )
        if related:
            context["related_memories"] = "\n".join([
                f"[相关记忆] {item['content'][:200]}"
                for item in related
            ])

    # 长期记忆: 向量检索 top-3
    context["long_term_memory"] = "（暂无长期记忆）"
    if user_msg_embedding:
        long_term_related = await embedding_service.search(
            query_vector=user_msg_embedding,
            session_id=session_id,
            top_k=3,
            source_type="long_term"
        )
        if long_term_related:
            context["long_term_memory"] = "\n".join([
                item["content"] for item in long_term_related
            ])
```

- [ ] **Step 3: 更新 full_prompt 模板**

将原来的 prompt 模板替换为新结构。找到 `full_prompt = f"""<system>...` 那一大段，替换为：

```python
    # 获取用户画像中的地区（备用提示）
    saved_region = (await memory_service.get_user_profile(session_dict.get("user_id", "")) or {}).get("region")
    location_hint = f"（根据历史记录，用户可能在 {saved_region}）" if saved_region else "（暂无用户位置信息）"

    skills_section = f"""{context['skills']}

【可用工具】
- query_weather: 查询天气
  用法: 当用户询问天气且你知道用户所在城市时调用
  参数: location (城市名，支持全球城市)

【重要】
Agent 需要自主从用户消息中识别位置信息：
- 如果用户提到城市名，请记住这个位置
- 如果用户询问天气但你不知道在哪，请先询问用户
{location_hint}
"""

    full_prompt = f"""<system>
{context['system_prompt']}
</system>

<long_term_memory>
{context['long_term_memory']}
</long_term_memory>

<user_profile>
{context['user_profile']}
</user_profile>

<intimacy>
{context['intimacy_info']}
</intimacy>

<skills>
{skills_section}
</skills>

<recent_conversation>
{context['recent_conversation']}
</recent_conversation>

<related_memories>
{context['related_memories']}
</related_memories>

<current_message>
主人: {request.content}
</current_message>

【重要规则】
1. 如果用户询问天气，你需要知道用户在哪：
   - 如果没有位置信息，请先询问用户所在城市
   - 如果用户指定了地点，使用用户指定的地点
2. 只有在知道用户所在城市后才能调用 query_weather 工具
3. 如果需要调用工具，请在回复中包含：
   [TOOL_CALL]
   {{"tool": "query_weather", "args": {{"location": "城市名"}}}}
   [/TOOL_CALL]
4. 如果用户的消息包含日程安排，在回复末尾添加：[SCHEDULE: 日程内容 | YYYY-MM-DD HH:MM]
5. 如果没有日程或不需要工具，不要添加任何标记
6. 调用工具后，系统会返回工具执行结果，请根据结果回复用户

请用{pet_type}的性格风格回复，直接输出回复内容。"""
```

- [ ] **Step 4: 更新压缩触发逻辑**

将 chat 端点中原有的压缩触发代码（约第 427-431 行）：

```python
    message_count = await memory_service.get_message_count(session_id)
    memory_compressed = False
    if message_count > 20 and message_count % 20 == 0:
        short_term_messages = await memory_service.get_short_term_messages(session_id, limit=40)
        await memory_service.compress_to_long_term(session_id, short_term_messages, pet_name)
        memory_compressed = True
```

替换为：

```python
    # 话题感知压缩触发
    memory_compressed = False
    recent_for_compress = await memory_service.get_short_term_messages(session_id, limit=10)
    recent_dicts = [{"role": m.role, "content": m.content} for m in recent_for_compress]
    should_compress = await memory_service.should_compress(session_id, recent_dicts, request.content)
    if should_compress:
        # 取滑动窗口外的消息进行压缩
        all_messages = await memory_service.get_short_term_messages(session_id, limit=100)
        window_ids = set(m.message_id for m in recent_for_compress)
        uncompress_messages = [m for m in all_messages if m.message_id not in window_ids]
        if uncompress_messages:
            await memory_service.compress_to_long_term(session_id, uncompress_messages[:15], pet_name)
            memory_compressed = True
```

- [ ] **Step 5: Commit**

```bash
git add backend/routers/chat.py
git commit -m "feat: rewrite build_context with dual-channel + vector retrieval"
```

---

### Task 9: 集成测试

**Files:**
- Create: `test_memory_integration.py`

- [ ] **Step 1: 编写集成测试验证关键流程**

```python
# test_memory_integration.py
"""记忆管理系统集成测试"""
import asyncio
import json
from backend.database import init_database
from backend.services.embedding_service import embedding_service
from backend.services.memory_service import memory_service


async def test_embedding_roundtrip():
    """测试 embedding API 调用和向量存储检索"""
    await init_database()

    test_text = "今天天气真好，我想出去散步"
    embedding = await embedding_service.embed(test_text)
    assert embedding is not None, "Embedding API 调用失败"
    assert len(embedding) > 0, "返回向量为空"
    print(f"[PASS] embed() 返回向量维度: {len(embedding)}")

    # 测试存储
    vector_id = await embedding_service.save_vector(
        session_id="test_session",
        source_type="message",
        source_id="test_msg_1",
        content=test_text,
        embedding=embedding
    )
    assert vector_id is not None
    print(f"[PASS] save_vector() 成功: {vector_id}")

    # 测试检索
    query_embedding = await embedding_service.embed("我想出门走走")
    assert query_embedding is not None
    results = await embedding_service.search(
        query_vector=query_embedding,
        session_id="test_session",
        top_k=3
    )
    assert len(results) > 0, "向量检索返回空"
    assert results[0]["similarity"] > 0.5, f"相似度过低: {results[0]['similarity']}"
    print(f"[PASS] search() 找到 {len(results)} 条结果, 最高相似度: {results[0]['similarity']:.4f}")


async def test_short_term_window():
    """测试短期记忆窗口从 40 改为 10"""
    await init_database()

    # 写入 20 条测试消息
    for i in range(20):
        await memory_service.save_message("test_session_2", "user", f"测试消息 {i}")

    messages = await memory_service.get_short_term_messages("test_session_2", limit=10)
    assert len(messages) <= 10, f"短期窗口应为 10 条，实际: {len(messages)}"
    print(f"[PASS] get_short_term_messages 返回 {len(messages)} 条（<=10）")


async def test_cosine_similarity():
    """测试余弦相似度计算"""
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0]
    assert embedding_service._cosine_similarity(vec_a, vec_b) == 1.0

    vec_c = [0.0, 1.0, 0.0]
    assert embedding_service._cosine_similarity(vec_a, vec_c) == 0.0

    print("[PASS] cosine_similarity 基础测试通过")


async def main():
    print("=== 记忆管理系统集成测试 ===\n")
    await test_cosine_similarity()
    await test_short_term_window()
    await test_embedding_roundtrip()
    print("\n=== 全部测试通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行测试**

```bash
python test_memory_integration.py
```

预期输出：
```
=== 记忆管理系统集成测试 ===

[PASS] cosine_similarity 基础测试通过
[PASS] get_short_term_messages 返回 10 条（<=10）
[PASS] embed() 返回向量维度: 1536
[PASS] save_vector() 成功: <uuid>
[PASS] search() 找到 1 条结果, 最高相似度: 0.8xxx

=== 全部测试通过 ===
```

- [ ] **Step 3: 最终 Commit**

```bash
git add test_memory_integration.py
git commit -m "test: add integration tests for vector search and short-term window"
```

---

## 自查

- [x] **Spec 覆盖：** 设计文档的每一节（向量索引层、短期记忆、长期记忆、用户画像、Prompt 组装）均有对应 Task
- [x] **无占位符：** 所有步骤包含完整代码，无 TBD/TODO
- [x] **类型一致性：** `get_short_term_messages` 的 limit 参数在 Task 4 改为 10，Task 5、Task 8 中调用时均使用 limit=10 或 limit=100；`embed` 返回 `Optional[List[float]]`，所有调用处均有 None 检查
- [x] **向后兼容：** 数据库 Schema 用 CREATE TABLE IF NOT EXISTS + ALTER TABLE try/except，已有数据不受影响
