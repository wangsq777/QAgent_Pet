import uuid
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from backend.database import get_db
from backend.schemas import MessageResponse
from backend.logging_config import get_logger

logger = get_logger(__name__)

# 用户画像允许更新的字段白名单（防止动态 SQL 字段名注入）
ALLOWED_PROFILE_FIELDS = {
    "region", "identity", "interests", "occupation",
    "personality_hint", "active_hours", "mood_tendency", "extra_info"
}

# 用户画像字段长度上限（防止 LLM 输出撑爆 prompt）
FIELD_MAX_LEN = {
    "region": 100,
    "identity": 50,
    "interests": 200,
    "occupation": 100,
    "personality_hint": 100,
    "active_hours": 100,
    "mood_tendency": 50,
    "extra_info": 500,
}

# 字段名格式校验（第二道防线）
FIELD_NAME_PATTERN = re.compile(r'^[a-z_]+$')

# 主 Agent 允许同步写入的画像字段（信任闸门：仅低风险、用户明示类字段）。
# 其余字段仍由后台画像 Agent 提取，防止用户消息借主 Agent 直接篡改画像。
MAIN_AGENT_PROFILE_FIELDS = {"region"}


class MemoryService:
    def __init__(self):
        # 画像内存缓存（写穿）：get_user_profile 每轮被调多次，写库后立即刷新
        self._profile_cache: Dict[str, Dict] = {}
    async def get_short_term_messages(self, session_id: str, limit: int = 10, before: Optional[int] = None) -> List[MessageResponse]:
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT m.message_id, m.role, m.content, m.emotion_tag, m.is_proactive, m.created_at, o.seq
                FROM messages m JOIN memory_message_order o USING(message_id)
                WHERE m.session_id = ? AND (? IS NULL OR o.seq < ?)
                ORDER BY o.seq DESC
                LIMIT ?
                """,
                (session_id, before, before, limit)
            )
            rows = await cursor.fetchall()
            return [MessageResponse(**dict(row)) for row in reversed(rows)]

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        emotion_tag: Optional[str] = None,
        is_proactive: bool = False,
        emotional_need: Optional[str] = None,
        emotion_intensity: Optional[int] = None,
        risk_level: Optional[str] = None
    ) -> str:
        message_id = str(uuid.uuid4())
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content, emotion_tag, is_proactive,
                                      emotional_need, emotion_intensity, risk_level, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, emotion_tag, is_proactive,
                 emotional_need, emotion_intensity, risk_level, datetime.now())
            )
            await db.execute('INSERT INTO memory_message_order(message_id,session_id) VALUES(?,?)',
                             (message_id,session_id))
            if role == 'user':
                from backend.services.memory_store import now
                await db.execute("INSERT OR IGNORE INTO memory_jobs(job_id,source_id,session_id,job_type,available_at) "
                                 "VALUES(?,?,?,'extract',?)",('extract:'+message_id,message_id,session_id,now()))
            await db.commit()
        return message_id

    async def get_message_count(self, session_id: str) -> int:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
                (session_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

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
            {"role": m["role"] if isinstance(m, dict) else m.role,
             "content": m["content"] if isinstance(m, dict) else m.content}
            for m in messages
        ]

        compressed = await llm_service.compress_memory(conversation_for_compress, pet_name)
        summary = compressed["summary"]
        importance = compressed.get("importance", 0.5)
        source_range = "messages:" + ",".join(
            str(m.get('message_id','unknown') if isinstance(m,dict) else m.message_id) for m in messages)

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

    async def detect_topic_change(self, recent_messages: List[Dict], current_message: str) -> bool:
        """用 LLM 检测当前消息是否与最近对话话题不同"""
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
            max_tokens=1000,
            caller="topic_detect"
        )

        if result:
            return "NO" in result.strip().upper()
        return False

    async def should_compress(self, session_id: str, recent_messages: List[Dict], current_message: str) -> bool:
        """Compatibility probe: use the same budget and checkpoint as the V2 worker."""
        from backend.config import settings
        from backend.services.memory_store import memory_store
        from backend.services.memory_context import context_builder
        identity = await memory_store.identity(session_id)
        recent = await context_builder.recent(identity,settings.MEMORY_SHORT_TOKENS//2)
        if not recent:
            return False
        async with get_db() as db:
            row = await (await db.execute('SELECT 1 FROM memory_message_order WHERE session_id=? AND seq<? '
                'AND seq>COALESCE((SELECT through_seq FROM conversation_checkpoints WHERE session_id=?),0) LIMIT 1',
                (session_id,recent[0]['seq'],session_id))).fetchone()
        return row is not None

    async def get_long_term_memories(self, session_id: str) -> List[Dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT memory_id, summary, source_range, created_at 
                FROM long_term_memories 
                WHERE session_id = ? 
                ORDER BY created_at DESC
                """,
                (session_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> None:
        async with get_db() as db:
            existing = await db.execute(
                "SELECT profile_id FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await existing.fetchone()
            
            if row:
                await db.execute(
                    """
                    UPDATE user_profiles 
                    SET region = COALESCE(?, region),
                        identity = COALESCE(?, identity),
                        interests = COALESCE(?, interests),
                        occupation = COALESCE(?, occupation),
                        personality_hint = COALESCE(?, personality_hint),
                        active_hours = COALESCE(?, active_hours),
                        mood_tendency = COALESCE(?, mood_tendency),
                        extra_info = COALESCE(?, extra_info),
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        profile_data.get("region"),
                        profile_data.get("identity"),
                        profile_data.get("interests"),
                        profile_data.get("occupation"),
                        profile_data.get("personality_hint"),
                        profile_data.get("active_hours"),
                        profile_data.get("mood_tendency"),
                        profile_data.get("extra_info"),
                        datetime.now(),
                        user_id
                    )
                )
            else:
                profile_id = str(uuid.uuid4())
                await db.execute(
                    """
                    INSERT INTO user_profiles (profile_id, user_id, region, identity, interests, occupation, personality_hint, active_hours, mood_tendency, extra_info, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        user_id,
                        profile_data.get("region"),
                        profile_data.get("identity"),
                        profile_data.get("interests"),
                        profile_data.get("occupation"),
                        profile_data.get("personality_hint"),
                        profile_data.get("active_hours"),
                        profile_data.get("mood_tendency"),
                        profile_data.get("extra_info"),
                        datetime.now(),
                        datetime.now()
                    )
                )
            await db.commit()
        await self._refresh_profile_cache(user_id)

    async def apply_main_agent_profile_update(self, user_id: str, update: Dict[str, Any]) -> bool:
        """
        信任闸门：应用主 Agent 在回复中声明的画像更新。
        仅放行 MAIN_AGENT_PROFILE_FIELDS 白名单字段，值经统一消毒截断，
        落库后同步刷新缓存并记录 profile_updated 事件。返回是否实际写入。
        """
        if not isinstance(update, dict):
            return False
        filtered = {}
        for field_name, value in update.items():
            if field_name not in MAIN_AGENT_PROFILE_FIELDS:
                if field_name in ALLOWED_PROFILE_FIELDS:
                    logger.info("主 Agent 画像字段 %s 不在同步写白名单，已忽略", field_name)
                else:
                    logger.warning("主 Agent 尝试写入非法画像字段: %s", field_name)
                continue
            sanitized = self._sanitize_profile_value(field_name, value)
            if sanitized is not None:
                filtered[field_name] = sanitized
        if not filtered:
            return False

        await self.merge_user_profile(user_id, filtered)

        from backend.services.event_service import event_service
        await event_service.append_event(
            user_id, None, "profile_updated",
            {"fields": filtered, "source": "main_agent"}
        )
        return True

    async def get_user_profile(self, user_id: str) -> Optional[Dict]:
        if user_id in self._profile_cache:
            return dict(self._profile_cache[user_id])
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
        profile = dict(row) if row else None
        if profile is not None:
            self._profile_cache[user_id] = profile
        return profile

    async def _refresh_profile_cache(self, user_id: str) -> None:
        """写库后刷新缓存（写穿），保证下一轮对话立即读到最新画像"""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
        if row:
            self._profile_cache[user_id] = dict(row)
        else:
            self._profile_cache.pop(user_id, None)

    def _sanitize_profile_value(self, field_name: str, value: Any) -> Optional[str]:
        """对用户画像字段值做长度截断与空值过滤"""
        if value is None or value == "" or value == "null":
            return None
        text = str(value).strip()
        if not text:
            return None
        limit = FIELD_MAX_LEN.get(field_name, 200)
        return text[:limit]

    async def merge_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> None:
        """
        合并用户画像（只更新非空的新值，保留已有值）。
        使用单事务 + 字段白名单，防止 SQL 注入与并发覆盖。
        """
        async with get_db() as db:
            existing = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await existing.fetchone()

            if row:
                update_fields = []
                update_values = []

                for field_name, new_value in profile_data.items():
                    # 白名单校验
                    if field_name not in ALLOWED_PROFILE_FIELDS:
                        logger.warning("忽略非法用户画像字段: %s", field_name)
                        continue
                    if not FIELD_NAME_PATTERN.match(field_name):
                        logger.warning("忽略格式非法的用户画像字段: %s", field_name)
                        continue
                    sanitized = self._sanitize_profile_value(field_name, new_value)
                    if sanitized is not None:
                        update_fields.append(f"{field_name} = ?")
                        update_values.append(sanitized)

                if update_fields:
                    update_fields.append("updated_at = ?")
                    update_values.append(datetime.now())
                    update_values.append(user_id)

                    await db.execute(
                        f"UPDATE user_profiles SET {', '.join(update_fields)} WHERE user_id = ?",
                        update_values
                    )
                    logger.debug("用户画像已更新: %s", profile_data)
                else:
                    logger.debug("用户画像无新数据，跳过更新")
            else:
                # 创建新记录
                profile_id = str(uuid.uuid4())
                insert_values = {
                    field: self._sanitize_profile_value(field, profile_data.get(field))
                    for field in ALLOWED_PROFILE_FIELDS
                }
                await db.execute(
                    """
                    INSERT INTO user_profiles (profile_id, user_id, region, identity, interests, occupation, personality_hint, active_hours, mood_tendency, extra_info, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        user_id,
                        insert_values.get("region"),
                        insert_values.get("identity"),
                        insert_values.get("interests"),
                        insert_values.get("occupation"),
                        insert_values.get("personality_hint"),
                        insert_values.get("active_hours"),
                        insert_values.get("mood_tendency"),
                        insert_values.get("extra_info"),
                        datetime.now(),
                        datetime.now()
                    )
                )
                logger.debug("用户画像已创建: %s", profile_data)

            await db.commit()
        await self._refresh_profile_cache(user_id)

    async def save_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> None:
        """
        直接保存用户画像（用于用户手动编辑，允许空值覆盖）
        """
        async with get_db() as db:
            existing = await db.execute(
                "SELECT profile_id FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await existing.fetchone()
            
            if row:
                await db.execute(
                    """
                    UPDATE user_profiles 
                    SET region = ?, identity = ?, interests = ?, occupation = ?, personality_hint = ?,
                        active_hours = ?, mood_tendency = ?, extra_info = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        profile_data.get("region"),
                        profile_data.get("identity"),
                        profile_data.get("interests"),
                        profile_data.get("occupation"),
                        profile_data.get("personality_hint"),
                        profile_data.get("active_hours"),
                        profile_data.get("mood_tendency"),
                        profile_data.get("extra_info"),
                        datetime.now(),
                        user_id
                    )
                )
            else:
                profile_id = str(uuid.uuid4())
                await db.execute(
                    """
                    INSERT INTO user_profiles (profile_id, user_id, region, identity, interests, occupation, personality_hint, active_hours, mood_tendency, extra_info, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        user_id,
                        profile_data.get("region"),
                        profile_data.get("identity"),
                        profile_data.get("interests"),
                        profile_data.get("occupation"),
                        profile_data.get("personality_hint"),
                        profile_data.get("active_hours"),
                        profile_data.get("mood_tendency"),
                        profile_data.get("extra_info"),
                        datetime.now(),
                        datetime.now()
                    )
                )
            await db.commit()
        await self._refresh_profile_cache(user_id)
        logger.debug("用户画像已保存: %s", profile_data)


memory_service = MemoryService()
