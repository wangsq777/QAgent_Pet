import re
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.schemas import ChatRequest, ChatResponse, MessageListResponse
from backend.services.llm_service import llm_service
from backend.services.memory_service import memory_service
from backend import prompts

router = APIRouter(prefix="/api/sessions", tags=["chat"])


def get_intimacy_level(intimacy: int) -> str:
    if intimacy <= 20:
        return "陌生"
    elif intimacy <= 50:
        return "熟悉"
    elif intimacy <= 80:
        return "亲密"
    else:
        return "挚友"


def calculate_intimacy_change(emotion_tag: str) -> int:
    if emotion_tag == "sad":
        return 3
    return 1


async def build_context(session_id: str, pet_type: str) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)

        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)

        long_term_memories = await memory_service.get_long_term_memories(session_id)
        long_term_text = "\n".join([m["summary"] for m in long_term_memories])

        user_profile = await memory_service.get_user_profile(session_dict["user_id"]) or {}

        short_term_messages = await memory_service.get_short_term_messages(session_id, limit=40)
        conversation_text = "\n".join([
            f"{'主人' if m['role'] == 'user' else pet_info.PET_NAME}: {m['content']}"
            for m in short_term_messages
        ])

        now = datetime.now()
        time_str = now.strftime("现在是%Y年%m月%d日 %H:%M")

        context = {
            "system_prompt": pet_info.get_system_prompt(),
            "long_term_memory": long_term_text or "（暂无长期记忆）",
            "user_profile": f"地区: {user_profile.get('region', '未知')}; 身份: {user_profile.get('identity', '未知')}; 兴趣: {user_profile.get('interests', '未知')}",
            "intimacy_info": f"亲密度: {session_dict['intimacy']} ({get_intimacy_level(session_dict['intimacy'])}); 共聊天: {session_dict['total_chats']}轮",
            "skills": f"当前时间: {time_str}",
            "conversation": conversation_text or "（暂无对话）"
        }

        return context


@router.post("/{session_id}/chat", response_model=ChatResponse)
async def chat(session_id: str, request: ChatRequest):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)
        pet_type = session_dict["pet_type"]

        if session_dict["pet_status"] == "hiding":
            status_until = session_dict.get("status_until")
            if status_until and datetime.now() < datetime.fromisoformat(status_until):
                return ChatResponse(
                    reply="（鼠鼠躲起来了，暂时不敢出来...）",
                    emotion_tag="neutral",
                    intimacy=session_dict["intimacy"],
                    total_chats=session_dict["total_chats"],
                    schedule_extracted=None,
                    memory_compressed=False
                )
            else:
                await db.execute(
                    "UPDATE pet_sessions SET pet_status = 'normal', updated_at = ? WHERE session_id = ?",
                    (datetime.now(), session_id)
                )
                session_dict["pet_status"] = "normal"

        if pet_type == "cold_cat" and session_dict["total_chats"] > 0:
            import random
            if random.random() < 0.3:
                return ChatResponse(
                    reply="......",
                    emotion_tag="neutral",
                    intimacy=session_dict["intimacy"],
                    total_chats=session_dict["total_chats"],
                    schedule_extracted=None,
                    memory_compressed=False
                )

    await memory_service.save_message(session_id, "user", request.content)

    context = await build_context(session_id, pet_type)

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
{context['skills']}
</skills>

<conversation>
{context['conversation']}

主人: {request.content}
</conversation>

【工具说明】
如果用户的消息包含日程安排（如约定时间、待办事项等），请在回复末尾添加日程标记：
[SCHEDULE: 日程内容 | YYYY-MM-DD HH:MM]
例如：用户说"明天十点开会"，回复末尾加上 [SCHEDULE: 开会 | 2026-04-28 10:00]
如果没有日程，不要添加任何标记。

请用{pet_type}的性格风格回复，直接输出回复内容。"""

    reply = await llm_service.chat([{"role": "user", "content": full_prompt}])
    if not reply:
        fallback_replies = {
            "hot_dog": "汪？主人，我突然不知道说什么了...",
            "cold_cat": "......不想说话。",
            "mouse": "鼠鼠我啊......突然不知道怎么回答了......"
        }
        reply = fallback_replies.get(pet_type, "突然不知道说什么了...")

    # 解析日程标记（支持有/无时间的情况）
    schedule_extracted = None
    schedule_pattern = r'\[SCHEDULE:\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2})?\]'
    match = re.search(schedule_pattern, reply)
    if match:
        schedule_extracted = {
            "content": match.group(1).strip(),
            "scheduled_time": match.group(2).strip()
        }
        reply = re.sub(schedule_pattern, '', reply).strip()  # 移除标记，只保留回复内容

    # 保存日程到数据库
    if schedule_extracted:
        schedule_id = str(uuid.uuid4())
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO schedules (schedule_id, session_id, content, scheduled_time, is_triggered, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (schedule_id, session_id, schedule_extracted["content"], schedule_extracted["scheduled_time"], 0, datetime.now())
            )
            await db.commit()
        print(f"[DEBUG] Schedule saved: {schedule_extracted}")

    # 继续原有的情绪提取（不再调用 extract_schedule）
    emotion_tag = await llm_service.extract_emotion(request.content, pet_type)

    await memory_service.save_message(session_id, "assistant", reply, emotion_tag=emotion_tag)

    intimacy_change = calculate_intimacy_change(emotion_tag)
    new_intimacy = min(100, session_dict["intimacy"] + intimacy_change)
    new_total_chats = session_dict["total_chats"] + 1

    message_count = await memory_service.get_message_count(session_id)
    memory_compressed = False
    if message_count > 20 and message_count % 20 == 0:
        short_term_messages = await memory_service.get_short_term_messages(session_id, limit=40)
        pet_prompts = {"hot_dog": prompts.hot_dog, "cold_cat": prompts.cold_cat, "mouse": prompts.mouse}
        pet_info = pet_prompts.get(pet_type)
        await memory_service.compress_to_long_term(session_id, short_term_messages, pet_info.PET_NAME)
        memory_compressed = True

    async with get_db() as db:
        await db.execute(
            "UPDATE pet_sessions SET intimacy = ?, total_chats = ?, last_interaction_at = ?, updated_at = ? WHERE session_id = ?",
            (new_intimacy, new_total_chats, datetime.now(), datetime.now(), session_id)
        )
        await db.commit()

    return ChatResponse(
        reply=reply,
        emotion_tag=emotion_tag,
        intimacy=new_intimacy,
        total_chats=new_total_chats,
        schedule_extracted=schedule_extracted,
        memory_compressed=memory_compressed
    )


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def get_messages(session_id: str):
    messages = await memory_service.get_short_term_messages(session_id, limit=100)
    return MessageListResponse(messages=messages, total=len(messages))