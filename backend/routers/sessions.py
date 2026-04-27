import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.schemas import SessionCreateRequest, SessionResponse, SimulateTimeRequest, SimulateTimeResponse, ErrorResponse, MemoryPanelResponse
from backend.services.llm_service import llm_service
from backend.services.memory_service import memory_service
from backend import prompts

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_intimacy_level(intimacy: int) -> str:
    if intimacy <= 20:
        return "陌生"
    elif intimacy <= 50:
        return "熟悉"
    elif intimacy <= 80:
        return "亲密"
    else:
        return "挚友"


@router.post("", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest):
    user_id = request.user_id
    pet_type = request.pet_type

    if pet_type not in ["hot_dog", "cold_cat", "mouse"]:
        raise HTTPException(status_code=400, detail="Invalid pet type")

    async with get_db() as db:
        # 查找该用户是否已有该宠物的 session
        cursor = await db.execute(
            "SELECT session_id FROM pet_sessions WHERE user_id = ? AND pet_type = ?",
            (user_id, pet_type)
        )
        existing = await cursor.fetchone()

        if existing:
            # 复用已有 session，直接返回欢迎消息（不重新生成）
            session_id = existing[0]
            cursor = await db.execute(
                "SELECT intimacy FROM pet_sessions WHERE session_id = ?",
                (session_id,)
            )
            session = await cursor.fetchone()
            intimacy = session[0] if session else 0

            return SessionResponse(
                session_id=session_id,
                pet_type=pet_type,
                welcome_message=None,  # 已有session不返回欢迎语
                intimacy=intimacy,
                is_existing=True  # 标记为已有session
            )

        # 创建新 session
        session_id = str(uuid.uuid4())

    async with get_db() as db:
        user_row = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user_exists = await user_row.fetchone()

        if not user_exists:
            nickname = request.nickname or "主人"
            await db.execute(
                "INSERT INTO users (user_id, nickname, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, nickname, datetime.now(), datetime.now())
            )
            profile_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO user_profiles (profile_id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (profile_id, user_id, datetime.now(), datetime.now())
            )

        await db.execute(
            """
            INSERT INTO pet_sessions (session_id, user_id, pet_type, intimacy, total_chats, last_interaction_at, pet_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, pet_type, 0, 0, datetime.now(), "normal", datetime.now(), datetime.now())
        )
        await db.commit()

    pet_prompts = {
        "hot_dog": prompts.hot_dog,
        "cold_cat": prompts.cold_cat,
        "mouse": prompts.mouse
    }
    pet_info = pet_prompts.get(pet_type)
    welcome_content = await llm_service.generate_welcome_message(
        pet_type,
        pet_info.PET_NAME,
        pet_info.PET_PERSONALITY
    )

    await memory_service.save_message(session_id, "assistant", welcome_content, is_proactive=True)

    return SessionResponse(
        session_id=session_id,
        pet_type=pet_type,
        welcome_message={
            "role": "assistant",
            "content": welcome_content,
            "created_at": datetime.now().isoformat()
        },
        intimacy=0
    )


@router.get("/{session_id}")
async def get_session(session_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return dict(session)


@router.post("/{session_id}/simulate-time", response_model=SimulateTimeResponse)
async def simulate_time(session_id: str, request: SimulateTimeRequest):
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
        pet_status = session_dict["pet_status"]
        last_interaction = session_dict.get("last_interaction_at")

        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)

        proactive_message = None
        new_status = pet_status

        # 默认回复
        default_messages = {
            "hot_dog": "汪！主人，我好想你呀！",
            "cold_cat": "......哼。",
            "mouse": "鼠鼠我啊......鼓起勇气来见主人了......"
        }

        if request.mode == "next_day":
            # 首先检查是否有待触发的日程
            cursor = await db.execute(
                "SELECT * FROM schedules WHERE session_id = ? AND is_triggered = 0 ORDER BY scheduled_time LIMIT 1",
                (session_id,)
            )
            schedule = await cursor.fetchone()
            
            if schedule:
                # 有日程，优先提醒日程
                schedule_dict = dict(schedule)
                schedule_content = f"提醒：{schedule_dict['content']}（时间: {schedule_dict['scheduled_time']}）"
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, schedule_content
                ) or f"{pet_info.PET_NAME}提醒你：{schedule_dict['content']}"
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)
                
                await db.execute(
                    "UPDATE schedules SET is_triggered = 1 WHERE schedule_id = ?",
                    (schedule_dict["schedule_id"],)
                )
            elif pet_type == "hot_dog":
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, "主人已经1天没互动了，我很想念主人！"
                ) or default_messages["hot_dog"]
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

            elif pet_type == "cold_cat":
                import random
                if random.random() < 0.5:
                    proactive_message = None
                else:
                    proactive_content = await llm_service.generate_proactive_message(
                        pet_type, pet_info.PET_NAME, "主人已经3天没互动了，我假装不在意但其实有点想主人。"
                    ) or default_messages["cold_cat"]
                    proactive_message = {"role": "assistant", "content": proactive_content}
                    await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

            elif pet_type == "mouse":
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, "主人已经2天没互动了，鼠鼠鼓起勇气打招呼。"
                ) or default_messages["mouse"]
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

        elif request.mode == "schedule_trigger":
            cursor = await db.execute(
                "SELECT * FROM schedules WHERE session_id = ? AND is_triggered = 0 ORDER BY scheduled_time LIMIT 1",
                (session_id,)
            )
            schedule = await cursor.fetchone()

            if schedule:
                schedule_dict = dict(schedule)
                schedule_content = f"提醒：{schedule_dict['content']}（时间: {schedule_dict['scheduled_time']}）"
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, schedule_content
                ) or f"{pet_info.PET_NAME}提醒你：{schedule_dict['content']}"
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

                await db.execute(
                    "UPDATE schedules SET is_triggered = 1 WHERE schedule_id = ?",
                    (schedule_dict["schedule_id"],)
                )

        await db.execute(
            "UPDATE pet_sessions SET last_interaction_at = ?, pet_status = ?, updated_at = ? WHERE session_id = ?",
            (datetime.now(), new_status, datetime.now(), session_id)
        )
        await db.commit()

        return SimulateTimeResponse(
            proactive_message=proactive_message,
            pet_status=new_status,
            schedule_reminder=None
        )


@router.get("/{session_id}/memory", response_model=MemoryPanelResponse)
async def get_memory_panel(session_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)
        intimacy = session_dict["intimacy"]
        total_chats = session_dict["total_chats"]

        intimacy_level = get_intimacy_level(intimacy)

        long_term_memories = await memory_service.get_long_term_memories(session_id)
        recent_messages_count = await memory_service.get_message_count(session_id)

        user_profile = await memory_service.get_user_profile(session_dict["user_id"]) or {}

        return MemoryPanelResponse(
            intimacy=intimacy,
            intimacy_level=intimacy_level,
            total_chats=total_chats,
            long_term_memories=long_term_memories,
            recent_messages_count=recent_messages_count,
            user_profile={
                "region": user_profile.get("region"),
                "identity": user_profile.get("identity"),
                "interests": user_profile.get("interests", "").split(",") if user_profile.get("interests") else [],
                "extra_info": user_profile.get("extra_info")
            }
        )