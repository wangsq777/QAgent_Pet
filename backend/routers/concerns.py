from fastapi import APIRouter, HTTPException, Request
from backend.database import get_db
from backend.schemas import ConcernCreateRequest, ConcernUpdateRequest
from backend.services.concern_service import confirm_concern, create_concern
from backend.services.time_service import utc_iso

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["concerns"])


async def _owned(db, session_id: str, user_id: str):
    cursor = await db.execute("SELECT user_id FROM pet_sessions WHERE session_id=?", (session_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row[0] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/concerns")
async def list_concerns(session_id: str, request: Request):
    async with get_db() as db:
        await _owned(db, session_id, request.state.user_id)
        cursor = await db.execute("SELECT * FROM concern_items WHERE session_id=? AND user_id=? ORDER BY updated_at_utc DESC", (session_id, request.state.user_id))
        return {"concerns": [dict(row) for row in await cursor.fetchall()]}


@router.post("/concerns")
async def add_concern(session_id: str, body: ConcernCreateRequest, request: Request):
    async with get_db() as db:
        await _owned(db, session_id, request.state.user_id)
        return await create_concern(db, user_id=request.state.user_id, session_id=session_id, **body.model_dump())


async def _get(db, session_id, concern_id, user_id):
    cursor = await db.execute("SELECT * FROM concern_items WHERE concern_id=? AND session_id=? AND user_id=?", (concern_id, session_id, user_id))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Concern not found")
    return dict(row)


@router.patch("/concerns/{concern_id}")
async def update_concern(session_id: str, concern_id: str, body: ConcernUpdateRequest, request: Request):
    async with get_db() as db:
        await _owned(db, session_id, request.state.user_id)
        concern = await _get(db, session_id, concern_id, request.state.user_id)
        values = body.model_dump(exclude_unset=True)
        if not values:
            return concern
        if "next_followup_at_utc" in values and values["next_followup_at_utc"] is not None:
            values["next_followup_at_utc"] = utc_iso(values["next_followup_at_utc"])
        assignments = [f"{key}=?" for key in values]
        params = list(values.values()) + [utc_iso(), concern_id]
        await db.execute(f"UPDATE concern_items SET {', '.join(assignments)}, updated_at_utc=? WHERE concern_id=?", params)
        await db.commit()
        return await _get(db, session_id, concern_id, request.state.user_id)


@router.delete("/concerns/{concern_id}")
async def delete_concern(session_id: str, concern_id: str, request: Request):
    async with get_db() as db:
        await _owned(db, session_id, request.state.user_id)
        await _get(db, session_id, concern_id, request.state.user_id)
        await db.execute("UPDATE concern_items SET status='dismissed', consent_state='denied', updated_at_utc=? WHERE concern_id=?", (utc_iso(), concern_id))
        await db.execute("UPDATE proactive_events SET status='cancelled', updated_at_utc=? WHERE source_type='concern' AND source_ref_id=? AND status NOT IN ('completed','cancelled','expired')", (utc_iso(), concern_id))
        await db.commit()
        return {"ok": True}


@router.post("/concerns/{concern_id}/confirm")
async def confirm(session_id: str, concern_id: str, request: Request):
    async with get_db() as db:
        await _owned(db, session_id, request.state.user_id)
        concern = await _get(db, session_id, concern_id, request.state.user_id)
        return await confirm_concern(db, concern)


@router.post("/concerns/{concern_id}/dismiss")
async def dismiss(session_id: str, concern_id: str, request: Request):
    async with get_db() as db:
        await _owned(db, session_id, request.state.user_id)
        await _get(db, session_id, concern_id, request.state.user_id)
        await db.execute("UPDATE concern_items SET status='dismissed', consent_state='denied', updated_at_utc=? WHERE concern_id=?", (utc_iso(), concern_id))
        await db.execute("UPDATE proactive_events SET status='cancelled', updated_at_utc=? WHERE source_type='concern' AND source_ref_id=?", (utc_iso(), concern_id))
        await db.commit()
        return {"ok": True}
