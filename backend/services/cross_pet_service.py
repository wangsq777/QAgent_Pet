import uuid
import json
from datetime import datetime
from typing import Optional
from backend.database import get_db
from backend.services.llm_service import llm_service
from backend.services.embedding_service import embedding_service
from backend.prompts.custom_pet import PRESET_PROMPTS, PET_TYPE_DISPLAY_NAMES
from backend.logging_config import get_logger
from backend.services.llm_service import _sanitize_prompt_input

logger = get_logger(__name__)

MAX_VISIT_MESSAGES = 20


class CrossPetService:

    async def get_pet_persona(self, pet_id_or_type: str, session_id: str = None) -> Optional[dict]:
        if pet_id_or_type in PRESET_PROMPTS:
            preset = PRESET_PROMPTS[pet_id_or_type]
            tags = preset["personality"]
            pet_type_display = PET_TYPE_DISPLAY_NAMES.get(preset["type"], preset["type"])
            catchphrase = preset.get("catchphrase", "")
            personality_summary = self._build_personality_summary(
                preset["name"], pet_type_display, tags, catchphrase
            )
            return {
                "pet_id": pet_id_or_type,
                "pet_name": preset["name"],
                "pet_type": preset["type"],
                "system_prompt": preset["system_prompt"],
                "personality_tags": tags,
                "catchphrase": catchphrase,
                "personality_summary": personality_summary,
            }

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT pet_id, pet_name, pet_type, personality_tags, catchphrase, system_prompt "
                "FROM custom_pets WHERE pet_id = ?",
                (pet_id_or_type,)
            )
            row = await cursor.fetchone()

        if not row:
            return None

        row_dict = dict(row)
        try:
            tags = json.loads(row_dict["personality_tags"])
        except Exception:
            tags = []

        pet_type_display = PET_TYPE_DISPLAY_NAMES.get(row_dict["pet_type"], "可爱小动物")
        catchphrase = row_dict.get("catchphrase") or ""
        personality_summary = self._build_personality_summary(
            row_dict["pet_name"], pet_type_display, tags, catchphrase
        )

        return {
            "pet_id": row_dict["pet_id"],
            "pet_name": row_dict["pet_name"],
            "pet_type": row_dict["pet_type"],
            "system_prompt": row_dict["system_prompt"],
            "personality_tags": tags,
            "catchphrase": catchphrase,
            "personality_summary": personality_summary,
        }

    def _build_personality_summary(
        self, pet_name: str, pet_type_display: str, tags: list, catchphrase: str
    ) -> str:
        summary = f"{pet_name}是一只{pet_type_display}，" \
                  f"性格{'、'.join(tags[:3]) if tags else '可爱'}。"
        if catchphrase:
            summary += f"口头禅是「{catchphrase}」。"
        return summary[:50]

    async def build_visit_prompt(
        self,
        speaker_persona: dict,
        visitor_persona: dict,
        topic: str,
        conversation_so_far: list,
        user_interjection: str = None
    ) -> str:
        conv_lines = "\n".join(
            [f"{m['speaker_name']}: {m['content']}" for m in conversation_so_far]
        )
        if not conv_lines:
            conv_lines = "（对话刚开始）"

        # VIS-2: 对话题和主人插话做 prompt 注入过滤
        topic_str = _sanitize_prompt_input(topic or "随便聊聊")[:100]

        interjection_section = ""
        if user_interjection:
            sanitized_interjection = _sanitize_prompt_input(user_interjection)[:200]
            interjection_section = f"\n<user_interjection>\n主人插话说：{sanitized_interjection}\n</user_interjection>\n"

        prompt = (
            f"<system>\n{speaker_persona['system_prompt']}\n</system>\n\n"
            f"<visit_context>\n"
            f"现在有另一只宠物来串门了！\n"
            f"来访宠物：{visitor_persona['pet_name']}\n"
            f"对方性格简介：{visitor_persona['personality_summary']}\n"
            f"串门话题：{topic_str}\n"
            f"</visit_context>\n\n"
            f"<conversation_so_far>\n{conv_lines}\n</conversation_so_far>\n"
            f"{interjection_section}\n"
            f"【规则】\n"
            f"1. 你只能扮演{speaker_persona['pet_name']}，不能模仿或扮演{visitor_persona['pet_name']}\n"
            f"2. 用你自己的性格风格说话，20-50字以内\n"
            f"3. 如果对方说了让你感兴趣的事，可以用符合性格的方式回应或追问\n"
            f"4. 不要暴露主人的私人信息\n"
            f"直接输出发言内容，不要加名字前缀。"
        )
        return prompt

    async def generate_visit_turn(
        self,
        visit_id: str,
        speaker: str,
        user_interjection: str = None
    ) -> Optional[str]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM pet_visits WHERE visit_id = ?",
                (visit_id,)
            )
            visit_row = await cursor.fetchone()

            if not visit_row:
                logger.error("visit_id not found: %s", visit_id)
                return None

            visit = dict(visit_row)

            cursor = await db.execute(
                "SELECT * FROM pet_visit_messages WHERE visit_id = ? ORDER BY turn_index ASC",
                (visit_id,)
            )
            msg_rows = await cursor.fetchall()
            messages = [dict(r) for r in msg_rows]

            # VIS-4 + VIS-5: 在同一事务内检查消息数上限，防止并发绕过
            cursor = await db.execute(
                "SELECT COUNT(*) FROM pet_visit_messages WHERE visit_id = ?",
                (visit_id,)
            )
            count_row = await cursor.fetchone()
            current_count = count_row[0] if count_row else 0
            if current_count >= MAX_VISIT_MESSAGES:
                logger.warning("Visit %s message limit reached", visit_id)
                raise ValueError(f"Visit message limit reached ({MAX_VISIT_MESSAGES} messages)")

        host_persona = await self._get_persona_from_session(visit["host_session_id"])

        guest_persona = await self.get_pet_persona(visit["guest_pet_id"])

        if not host_persona or not guest_persona:
            logger.error("Could not load personas for visit %s", visit_id)
            return None

        if speaker == "host":
            speaker_persona = host_persona
            visitor_persona = guest_persona
        else:
            speaker_persona = guest_persona
            visitor_persona = host_persona

        topic = visit.get("topic") or "随便聊聊"
        prompt = await self.build_visit_prompt(
            speaker_persona=speaker_persona,
            visitor_persona=visitor_persona,
            topic=topic,
            conversation_so_far=messages,
            user_interjection=user_interjection
        )

        llm_messages = [{"role": "user", "content": prompt}]
        result = await llm_service.chat(
            llm_messages, temperature=0.9, max_tokens=200, caller="visit_turn"
        )

        if not result:
            result = f"......{speaker_persona['pet_name']}想了想，好像不知道说什么。"

        result = self._remove_name_prefix(result, speaker_persona["pet_name"])
        result = self._remove_other_name_prefix(result, visitor_persona["pet_name"])

        turn_index = len(messages)
        msg_id = str(uuid.uuid4())

        async with get_db() as db:
            await db.execute(
                "INSERT INTO pet_visit_messages "
                "(msg_id, visit_id, speaker_pet_id, speaker_name, content, turn_index, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, visit_id, speaker_persona["pet_id"],
                 speaker_persona["pet_name"], result, turn_index, datetime.now())
            )
            await db.commit()

        return result

    def _remove_name_prefix(self, text: str, pet_name: str) -> str:
        if text.startswith(f"{pet_name}:") or text.startswith(f"{pet_name}："):
            return text[len(pet_name) + 1:].strip()
        return text

    def _remove_other_name_prefix(self, text: str, other_name: str) -> str:
        for sep in (":", "："):
            prefix = f"{other_name}{sep}"
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    async def end_visit(self, visit_id: str, save_memory: bool = True) -> dict:
        async with get_db() as db:
            await db.execute(
                "UPDATE pet_visits SET status = 'ended', ended_at = ? WHERE visit_id = ?",
                (datetime.now(), visit_id)
            )
            await db.commit()

        result = {"host_memory_saved": False, "guest_memory_saved": False}

        if not save_memory:
            return result

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM pet_visits WHERE visit_id = ?", (visit_id,)
            )
            visit_row = await cursor.fetchone()
            if not visit_row:
                return result
            visit = dict(visit_row)

            cursor = await db.execute(
                "SELECT * FROM pet_visit_messages WHERE visit_id = ? ORDER BY turn_index ASC",
                (visit_id,)
            )
            msg_rows = await cursor.fetchall()
            messages = [dict(r) for r in msg_rows]

        if not messages:
            return result

        conv_text = "\n".join([f"{m['speaker_name']}: {m['content']}" for m in messages])

        host_persona = await self._get_persona_from_session(visit["host_session_id"])
        guest_persona = await self.get_pet_persona(visit["guest_pet_id"])

        summary_prompt = (
            f"以下是两只宠物之间的一段串门对话：\n{conv_text}\n\n"
            f"请用100字以内总结这段对话的亮点，包括聊了什么话题、有什么有趣的互动。"
            f"只输出摘要，不要额外说明。"
        )
        llm_messages = [{"role": "user", "content": summary_prompt}]
        summary = await llm_service.chat(
            llm_messages, temperature=0.5, max_tokens=300, caller="visit_summary"
        )
        if not summary:
            summary = f"和{guest_persona['pet_name'] if guest_persona else '朋友'}的一次串门对话。"

        source_range = f"visit:{visit_id}"

        if host_persona and host_persona.get("session_id"):
            memory_id = await self._save_visit_memory(
                session_id=host_persona["session_id"],
                summary=summary,
                source_range=source_range
            )
            result["host_memory_saved"] = bool(memory_id)

        if visit.get("guest_session_id"):
            # VIS-6: 写入 guest 记忆前验证该 session 属于串门发起者
            guest_session_owner = await self._get_session_user_id(visit["guest_session_id"])
            if guest_session_owner == visit["initiator_user_id"]:
                memory_id = await self._save_visit_memory(
                    session_id=visit["guest_session_id"],
                    summary=summary,
                    source_range=source_range
                )
                result["guest_memory_saved"] = bool(memory_id)
            else:
                logger.warning(
                    "拒绝将串门记忆写入不归属的 guest session %s (owner=%s, initiator=%s)",
                    visit["guest_session_id"],
                    guest_session_owner,
                    visit["initiator_user_id"]
                )

        return result

    async def _get_session_user_id(self, session_id: str) -> Optional[str]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT user_id FROM pet_sessions WHERE session_id = ?",
                (session_id,)
            )
            row = await cursor.fetchone()
        return row["user_id"] if row else None

    async def _batch_get_pet_names_by_sessions(self, session_ids: list) -> dict:
        """批量根据 session_id 查询宠物名称，返回 {session_id: pet_name}"""
        if not session_ids:
            return {}
        placeholders = ", ".join("?" * len(session_ids))
        async with get_db() as db:
            cursor = await db.execute(
                f"SELECT session_id, pet_type, custom_pet_id FROM pet_sessions WHERE session_id IN ({placeholders})",
                tuple(session_ids)
            )
            rows = await cursor.fetchall()

        result = {}
        for row in rows:
            sess = dict(row)
            persona = await self.get_pet_persona(
                sess["custom_pet_id"] if sess["pet_type"] == "custom" and sess["custom_pet_id"] else sess["pet_type"]
            )
            result[sess["session_id"]] = persona["pet_name"] if persona else None
        return result

    async def _batch_get_pet_names_by_pets(self, pet_ids: list) -> dict:
        """批量根据 pet_id（含预置类型名）查询宠物名称，返回 {pet_id: pet_name}"""
        if not pet_ids:
            return {}
        result = {}
        custom_ids = []
        for pid in pet_ids:
            if pid in PRESET_PROMPTS:
                result[pid] = PRESET_PROMPTS[pid]["name"]
            else:
                custom_ids.append(pid)

        if custom_ids:
            placeholders = ", ".join("?" * len(custom_ids))
            async with get_db() as db:
                cursor = await db.execute(
                    f"SELECT pet_id, pet_name FROM custom_pets WHERE pet_id IN ({placeholders})",
                    tuple(custom_ids)
                )
                rows = await cursor.fetchall()
            for row in rows:
                result[row["pet_id"]] = row["pet_name"]

        return result

    async def _get_persona_from_session(self, session_id: str) -> Optional[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT pet_type, custom_pet_id FROM pet_sessions WHERE session_id = ?",
                (session_id,)
            )
            row = await cursor.fetchone()
        if not row:
            return None
        sess = dict(row)
        if sess["pet_type"] == "custom" and sess["custom_pet_id"]:
            persona = await self.get_pet_persona(sess["custom_pet_id"])
        else:
            persona = await self.get_pet_persona(sess["pet_type"])
        if persona:
            persona["session_id"] = session_id
        return persona

    async def _save_visit_memory(self, session_id: str, summary: str, source_range: str) -> Optional[str]:
        memory_id = str(uuid.uuid4())
        async with get_db() as db:
            await db.execute(
                "INSERT INTO long_term_memories (memory_id, session_id, summary, source_range, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (memory_id, session_id, summary, source_range, datetime.now())
            )
            await db.commit()

        embedding = await embedding_service.embed(summary)
        if embedding:
            await embedding_service.save_vector(
                session_id=session_id,
                source_type="long_term",
                source_id=memory_id,
                content=summary,
                embedding=embedding,
                importance=0.6
            )

        return memory_id


cross_pet_service = CrossPetService()
