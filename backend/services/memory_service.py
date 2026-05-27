import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from backend.database import get_db
from backend.schemas import MessageResponse


class MemoryService:
    async def get_short_term_messages(self, session_id: str, limit: int = 10) -> List[MessageResponse]:
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
            return [MessageResponse(**dict(row)) for row in reversed(rows)]

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
        messages: List,
        pet_name: str
    ) -> Optional[str]:
        from backend.services.llm_service import llm_service
        
        memory_id = str(uuid.uuid4())
        conversation_for_compress = [
            {"role": getattr(m, "role", m.get("role")), "content": getattr(m, "content", m.get("content"))}
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

    async def merge_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> None:
        """
        合并用户画像（只更新非空的新值，保留已有值）
        """
        async with get_db() as db:
            existing = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await existing.fetchone()
            
            if row:
                existing_data = dict(row)
                # 合并：只有新值非空才更新
                new_region = profile_data.get("region")
                new_identity = profile_data.get("identity")
                new_interests = profile_data.get("interests")
                new_extra_info = profile_data.get("extra_info")
                
                update_fields = []
                update_values = []
                
                if new_region is not None and new_region != "" and new_region != "null":
                    update_fields.append("region = ?")
                    update_values.append(new_region)
                if new_identity is not None and new_identity != "" and new_identity != "null":
                    update_fields.append("identity = ?")
                    update_values.append(new_identity)
                if new_interests is not None and new_interests != "" and new_interests != "null":
                    update_fields.append("interests = ?")
                    update_values.append(new_interests)
                if new_extra_info is not None and new_extra_info != "" and new_extra_info != "null":
                    update_fields.append("extra_info = ?")
                    update_values.append(new_extra_info)
                
                if update_fields:
                    update_fields.append("updated_at = ?")
                    update_values.append(datetime.now())
                    update_values.append(user_id)
                    
                    await db.execute(
                        f"UPDATE user_profiles SET {', '.join(update_fields)} WHERE user_id = ?",
                        update_values
                    )
                    print(f"[MemoryService] 用户画像已更新: {profile_data}")
                else:
                    print(f"[MemoryService] 用户画像无新数据，跳过更新")
            else:
                # 创建新记录
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
                print(f"[MemoryService] 用户画像已创建: {profile_data}")
            
            await db.commit()

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
                    SET region = ?, identity = ?, interests = ?, extra_info = ?, updated_at = ?
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
            print(f"[MemoryService] 用户画像已保存: {profile_data}")


memory_service = MemoryService()