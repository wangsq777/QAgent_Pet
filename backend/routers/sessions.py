import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.schemas import SessionCreateRequest, SessionResponse, SimulateTimeRequest, SimulateTimeResponse, ErrorResponse
from backend.services.llm_service import llm_service
from backend.services.memory_service import memory_service
from backend import prompts

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest):
    session_id = str(uuid.uuid4())
    user_id = request.user_id
    pet_type = request.pet_type

    if pet_type not in ["hot_dog", "cold_cat", "mouse"]:
        raise HTTPException(status_code=400, detail="Invalid pet type")

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

        if request.mode == "next_day":
            if pet_type == "hot_dog":
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, "主人已经1天没互动了，我很想念主人！"
                )
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

            elif pet_type == "cold_cat":
                import random
                if random.random() < 0.5:
                    proactive_message = None
                else:
                    proactive_content = await llm_service.generate_proactive_message(
                        pet_type, pet_info.PET_NAME, "主人已经3天没互动了，我假装不在意但其实有点想主人。"
                    )
                    proactive_message = {"role": "assistant", "content": proactive_content}
                    await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

            elif pet_type == "mouse":
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, "主人已经2天没互动了，鼠鼠鼓起勇气打招呼。"
                )
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
                )
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