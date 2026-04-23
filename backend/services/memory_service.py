import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from backend.database import get_db


class MemoryService:
    async def get_short_term_messages(self, session_id: str, limit: int = 40) -> List[Dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT message_id, role, content, emotion_tag, is_proactive, created_at 
                FROM messages 
                WHERE session_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (session_id, limit)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in reversed(rows)]

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        emotion_tag: Optional[str] = None,
        is_proactive: bool = False
    ) -> str:
        message_id = str(uuid.uuid4())
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content, emotion_tag, is_proactive, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, emotion_tag, is_proactive, datetime.now())
            )
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
        messages: List[Dict],
        pet_name: str
    ) -> Optional[str]:
        from backend.services.llm_service import llm_service
        
        memory_id = str(uuid.uuid4())
        conversation_for_compress = [
            {"role": m["role"], "content": m["content"]}
            for m in messages[:20]
        ]
        
        summary = await llm_service.compress_memory(conversation_for_compress, pet_name)
        source_range = f"轮次1-{min(len(messages), 20)}"
        
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO long_term_memories (memory_id, session_id, summary, source_range, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (memory_id, session_id, summary, source_range, datetime.now())
            )
            await db.commit()
        
        return memory_id

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
                        extra_info = COALESCE(?, extra_info),
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        profile_data.get("region"),
                        profile_data.get("identity"),
                        profile_data.get("interests"),
                        profile_data.get("extra_info"),
                        datetime.now(),
                        user_id
                    )
                )
            else:
                profile_id = str(uuid.uuid4())
                await db.execute(
                    """
                    INSERT INTO user_profiles (profile_id, user_id, region, identity, interests, extra_info, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        user_id,
                        profile_data.get("region"),
                        profile_data.get("identity"),
                        profile_data.get("interests"),
                        profile_data.get("extra_info"),
                        datetime.now(),
                        datetime.now()
                    )
                )
            await db.commit()

    async def get_user_profile(self, user_id: str) -> Optional[Dict]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None


memory_service = MemoryService()