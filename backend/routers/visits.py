import uuid
import re
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.database import get_db
from backend.services.cross_pet_service import cross_pet_service, MAX_VISIT_MESSAGES
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/visits", tags=["visits"])
limiter = Limiter(key_func=get_remote_address)

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def _validate_uuid(value: str, field_name: str = "id") -> None:
    if not value or not UUID_PATTERN.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")


class StartVisitRequest(BaseModel):
    host_session_id: str
    guest_pet_id: str
    topic: Optional[str] = Field(None, max_length=100)


class NextTurnRequest(BaseModel):
    user_interjection: Optional[str] = Field("", max_length=200)
    next_speaker: str = "auto"


class EndVisitRequest(BaseModel):
    save_memory: bool = True


@router.post("")
@limiter.limit("5/minute")
async def start_visit(body: StartVisitRequest, request: Request):
    user_id = request.state.user_id
    _validate_uuid(body.host_session_id, "host_session_id")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT session_id, pet_type, custom_pet_id, user_id FROM pet_sessions WHERE session_id = ?",
            (body.host_session_id,)
        )
        host_sess_row = await cursor.fetchone()

    if not host_sess_row:
        raise HTTPException(status_code=404, detail="Host session not found")

    host_sess = dict(host_sess_row)
    if host_sess["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    host_persona = await cross_pet_service._get_persona_from_session(body.host_session_id)
    if not host_persona:
        raise HTTPException(status_code=400, detail="Unable to load host pet persona")

    # VIS-1: 非预置宠物必须属于当前用户
    is_preset_guest = body.guest_pet_id in ("hot_dog", "cold_cat", "mouse")
    if not is_preset_guest:
        _validate_uuid(body.guest_pet_id, "guest_pet_id")
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT pet_id FROM custom_pets WHERE pet_id = ? AND user_id = ?",
                (body.guest_pet_id, user_id)
            )
            if not await cursor.fetchone():
                raise HTTPException(status_code=403, detail="Guest pet not accessible")

    guest_persona = await cross_pet_service.get_pet_persona(body.guest_pet_id)
    if not guest_persona:
        raise HTTPException(status_code=404, detail="Guest pet not found")

    guest_session_id = None
    if not is_preset_guest:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT session_id FROM pet_sessions WHERE custom_pet_id = ? AND user_id = ? LIMIT 1",
                (body.guest_pet_id, user_id)
            )
            gsess_row = await cursor.fetchone()
        if gsess_row:
            guest_session_id = dict(gsess_row)["session_id"]

    visit_id = str(uuid.uuid4())

    # VIS-5: 单事务内结束已有 active visit 并创建新 visit，避免 TOCTOU
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT visit_id FROM pet_visits WHERE host_session_id = ? AND status = 'active'",
            (body.host_session_id,)
        )
        existing_row = await cursor.fetchone()
        if existing_row:
            old_visit_id = dict(existing_row)["visit_id"]
            await db.execute(
                "UPDATE pet_visits SET status = 'ended', ended_at = ? WHERE visit_id = ?",
                (datetime.now(), old_visit_id)
            )
            logger.info("Auto-ended previous active visit %s before creating new one", old_visit_id)

        await db.execute(
            "INSERT INTO pet_visits "
            "(visit_id, host_session_id, guest_pet_id, guest_session_id, initiator_user_id, topic, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
            (visit_id, body.host_session_id, body.guest_pet_id,
             guest_session_id, user_id, body.topic, datetime.now())
        )
        await db.commit()

    opening_content = await cross_pet_service.generate_visit_turn(
        visit_id=visit_id, speaker="host"
    )

    return {
        "visit_id": visit_id,
        "host_pet_name": host_persona["pet_name"],
        "guest_pet_name": guest_persona["pet_name"],
        "opening_message": {
            "speaker": host_persona["pet_name"],
            "content": opening_content,
            "turn_index": 0
        }
    }


@router.post("/{visit_id}/next")
@limiter.limit("30/minute")
async def next_turn(visit_id: str, body: NextTurnRequest, request: Request):
    user_id = request.state.user_id
    _validate_uuid(visit_id, "visit_id")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_visits WHERE visit_id = ?", (visit_id,)
        )
        visit_row = await cursor.fetchone()

    if not visit_row:
        raise HTTPException(status_code=404, detail="Visit not found")

    visit = dict(visit_row)
    if visit["initiator_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if visit["status"] != "active":
        raise HTTPException(status_code=400, detail="Visit has ended")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM pet_visit_messages WHERE visit_id = ?", (visit_id,)
        )
        count_row = await cursor.fetchone()
    msg_count = count_row[0] if count_row else 0

    if body.next_speaker in ("host", "guest"):
        speaker = body.next_speaker
    else:
        speaker = "host" if msg_count % 2 == 0 else "guest"

    interjection = body.user_interjection or None

    try:
        content = await cross_pet_service.generate_visit_turn(
            visit_id=visit_id, speaker=speaker, user_interjection=interjection
        )
    except ValueError as e:
        if "limit reached" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        raise

    guest_persona = await cross_pet_service.get_pet_persona(visit["guest_pet_id"])
    host_persona = await cross_pet_service._get_persona_from_session(visit["host_session_id"])

    # VIS-7: None 保护
    if not host_persona or not guest_persona:
        raise HTTPException(status_code=400, detail="Unable to load pet persona")

    speaker_name = host_persona["pet_name"] if speaker == "host" else guest_persona["pet_name"]

    return {
        "message": {
            "speaker": speaker_name,
            "content": content,
            "turn_index": msg_count
        },
        "visit_status": "active"
    }


@router.get("/{visit_id}/messages")
@limiter.limit("60/minute")
async def get_visit_messages(visit_id: str, request: Request):
    user_id = request.state.user_id
    _validate_uuid(visit_id, "visit_id")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT initiator_user_id FROM pet_visits WHERE visit_id = ?", (visit_id,)
        )
        visit_row = await cursor.fetchone()

    if not visit_row:
        raise HTTPException(status_code=404, detail="Visit not found")

    if dict(visit_row)["initiator_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT msg_id, speaker_pet_id, speaker_name, content, turn_index, created_at "
            "FROM pet_visit_messages WHERE visit_id = ? ORDER BY turn_index ASC",
            (visit_id,)
        )
        rows = await cursor.fetchall()

    return {
        "visit_id": visit_id,
        "messages": [dict(r) for r in rows]
    }


@router.post("/{visit_id}/end")
@limiter.limit("10/minute")
async def end_visit(visit_id: str, body: EndVisitRequest, request: Request):
    user_id = request.state.user_id
    _validate_uuid(visit_id, "visit_id")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_visits WHERE visit_id = ?", (visit_id,)
        )
        visit_row = await cursor.fetchone()

    if not visit_row:
        raise HTTPException(status_code=404, detail="Visit not found")

    visit = dict(visit_row)
    if visit["initiator_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if visit["status"] == "ended":
        return {"status": "ended", "host_memory_saved": False, "guest_memory_saved": False}

    memory_result = await cross_pet_service.end_visit(visit_id, save_memory=body.save_memory)

    return {
        "status": "ended",
        **memory_result
    }


@router.get("")
@limiter.limit("60/minute")
async def list_visits(request: Request):
    user_id = request.state.user_id

    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT v.visit_id, v.host_session_id, v.guest_pet_id, v.guest_session_id,
                   v.topic, v.status, v.created_at, v.ended_at,
                   (SELECT COUNT(*) FROM pet_visit_messages WHERE visit_id = v.visit_id) AS message_count
            FROM pet_visits v
            WHERE v.initiator_user_id = ?
            ORDER BY v.created_at DESC
            LIMIT 20
            """,
            (user_id,)
        )
        rows = await cursor.fetchall()

    visits = []
    if rows:
        # VIS-8: 批量查询 host session 与 guest pet 的宠物名称，避免 N+1
        host_session_ids = []
        guest_pet_ids = []
        for row in rows:
            v = dict(row)
            visits.append(v)
            host_session_ids.append(v["host_session_id"])
            guest_pet_ids.append(v["guest_pet_id"])

        host_names = await cross_pet_service._batch_get_pet_names_by_sessions(host_session_ids)
        guest_names = await cross_pet_service._batch_get_pet_names_by_pets(guest_pet_ids)

        for v in visits:
            v["host_pet_name"] = host_names.get(v["host_session_id"], "已删除")
            v["guest_pet_name"] = guest_names.get(v["guest_pet_id"], "已删除")

    return {"visits": visits}
