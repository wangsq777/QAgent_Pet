from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request

from backend.database import get_db
from backend.schemas import ScheduleCandidateConfirmRequest, ScheduleCreateRequest, ScheduleUpdateRequest
from backend.services.schedule_service import create_schedule, normalize_schedule_time
from backend.services.time_service import utc_iso

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["schedules"])


async def _owned_session(db, session_id: str, user_id: str):
    cursor = await db.execute("SELECT session_id,user_id FROM pet_sessions WHERE session_id=?", (session_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row[1] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/schedules")
async def list_schedules(session_id: str, request: Request):
    async with get_db() as db:
        await _owned_session(db, session_id, request.state.user_id)
        cursor = await db.execute("SELECT * FROM schedules WHERE session_id=? ORDER BY COALESCE(scheduled_at_utc, scheduled_time)", (session_id,))
        return {"schedules": [dict(row) for row in await cursor.fetchall()]}


@router.post("/schedules")
async def add_schedule(session_id: str, body: ScheduleCreateRequest, request: Request):
    async with get_db() as db:
        await _owned_session(db, session_id, request.state.user_id)
        try:
            when = normalize_schedule_time(scheduled_at=body.scheduled_at, scheduled_at_utc=body.scheduled_at_utc, timezone=body.timezone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        result = await create_schedule(db, user_id=request.state.user_id, session_id=session_id, content=body.content, scheduled_at_utc=when, timezone=body.timezone, reminder_offset_minutes=body.reminder_offset_minutes, origin=body.origin)
        await db.commit()
        return result


@router.patch("/schedules/{schedule_id}")
async def update_schedule(session_id: str, schedule_id: str, body: ScheduleUpdateRequest, request: Request):
    async with get_db() as db:
        await _owned_session(db, session_id, request.state.user_id)
        cursor = await db.execute("SELECT * FROM schedules WHERE schedule_id=? AND session_id=?", (schedule_id, session_id))
        schedule = await cursor.fetchone()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        values = body.model_dump(exclude_unset=True)
        if "scheduled_at" in values or "scheduled_at_utc" in values:
            values["scheduled_at_utc"] = utc_iso(normalize_schedule_time(scheduled_at=values.pop("scheduled_at", None), scheduled_at_utc=values.pop("scheduled_at_utc", None), timezone=values.get("timezone") or schedule["timezone"] or "Asia/Shanghai"))
            values["scheduled_time"] = values["scheduled_at_utc"]
        if "timezone" in values and values["timezone"] is None:
            values.pop("timezone")
        if not values:
            return dict(schedule)
        assignments = []
        params = []
        for key, value in values.items():
            if key in {"content", "scheduled_at_utc", "scheduled_time", "timezone", "status", "reminder_offset_minutes"}:
                assignments.append(f"{key}=?")
                params.append(value)
        if "status" in values:
            params.extend([1 if values["status"] == "completed" else 0])
            assignments.append("is_triggered=?")
        params.extend([schedule_id, session_id])
        await db.execute(f"UPDATE schedules SET {', '.join(assignments)} WHERE schedule_id=? AND session_id=?", params)
        if "status" in values and values["status"] == "cancelled":
            await db.execute("UPDATE proactive_events SET status='cancelled', updated_at_utc=? WHERE source_type='schedule' AND source_ref_id=? AND status NOT IN ('completed','cancelled','expired')", (utc_iso(), schedule_id))
        elif "scheduled_at_utc" in values:
            await db.execute("UPDATE proactive_events SET scheduled_at_utc=?, status=CASE WHEN status='cancelled' THEN status ELSE 'pending' END, updated_at_utc=? WHERE source_type='schedule' AND source_ref_id=?", (values["scheduled_at_utc"], utc_iso(), schedule_id))
        await db.commit()
        cursor = await db.execute("SELECT * FROM schedules WHERE schedule_id=?", (schedule_id,))
        return dict(await cursor.fetchone())


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(session_id: str, schedule_id: str, request: Request):
    async with get_db() as db:
        await _owned_session(db, session_id, request.state.user_id)
        cursor = await db.execute("SELECT schedule_id FROM schedules WHERE schedule_id=? AND session_id=?", (schedule_id, session_id))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")
        await db.execute("UPDATE schedules SET status='cancelled' WHERE schedule_id=? AND session_id=?", (schedule_id, session_id))
        await db.execute("UPDATE proactive_events SET status='cancelled', updated_at_utc=? WHERE source_type='schedule' AND source_ref_id=? AND status NOT IN ('completed','cancelled','expired')", (utc_iso(), schedule_id))
        await db.commit()
        return {"ok": True}


@router.post("/schedule-candidates/{candidate_id}/confirm")
async def confirm_candidate(session_id: str, candidate_id: str, body: ScheduleCandidateConfirmRequest, request: Request):
    async with get_db() as db:
        await _owned_session(db, session_id, request.state.user_id)
        cursor = await db.execute("SELECT * FROM schedule_candidates WHERE candidate_id=? AND session_id=? AND user_id=? AND status='pending'", (candidate_id, session_id, request.state.user_id))
        candidate = await cursor.fetchone()
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        timezone = body.timezone or candidate["timezone"]
        schedule = await create_schedule(db, user_id=request.state.user_id, session_id=session_id, content=candidate["content"], scheduled_at_utc=normalize_schedule_time(scheduled_at=body.scheduled_at, scheduled_at_utc=None, timezone=timezone), timezone=timezone, origin="chat_inferred", source_message_id=candidate["source_message_id"])
        await db.execute("UPDATE schedule_candidates SET status='confirmed', updated_at_utc=? WHERE candidate_id=?", (utc_iso(), candidate_id))
        await db.commit()
        return schedule
