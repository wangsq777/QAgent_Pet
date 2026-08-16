from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.database import get_db
from backend.schemas import ProactiveActionRequest, ProactiveClaimRequest, ProactiveReceiptRequest, ProactiveSettingsRequest
from backend.services.proactive_service import claim_event, ensure_settings, get_owned_event, record_event
from backend.services.time_service import ensure_utc, utc_iso

router = APIRouter(prefix="/api/proactive", tags=["proactive"])
limiter = Limiter(key_func=get_remote_address)


def _public(event: dict) -> dict:
    context = {}
    try:
        import json
        context = json.loads(event.get("message_context_json") or "{}")
    except Exception:
        pass
    full = event.get("rendered_message") or context.get("full_message") or f"{context.get('subject') or context.get('content') or '我来看看你。'}"
    return {"event_id": event["event_id"], "claim_token": event.get("claim_token"), "source_type": event["source_type"],
            "bubble_text": event["bubble_text"], "full_message": full,
            "suggested_actions": ["acknowledge", "snooze_10m", "snooze_1h", "complete", "dismiss"],
            "scheduled_at_utc": event.get("scheduled_at_utc"), "status": event.get("status")}


@router.post("/events/claim")
@limiter.limit("60/minute")
async def claim(body: ProactiveClaimRequest, request: Request):
    async with get_db() as db:
        # session 归属校验，不信任请求体 user_id
        cursor = await db.execute("SELECT user_id FROM pet_sessions WHERE session_id=?", (body.session_id,))
        session = await cursor.fetchone()
        if not session or session[0] != request.state.user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        await ensure_settings(db, request.state.user_id, body.timezone)
        event = await claim_event(db, user_id=request.state.user_id, session_id=body.session_id, timezone=body.timezone, client_id=body.client_id)
        return {"event": _public(event) if event else None}


async def _receipt(event_id: str, body: ProactiveReceiptRequest, request: Request, target: str):
    async with get_db() as db:
        event = await get_owned_event(db, event_id, request.state.user_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        try:
            updated = await record_event(db, event_id, request.state.user_id, target, claim_token=body.claim_token, **({"delivered_at_utc": utc_iso()} if target == "delivered" else {"opened_at_utc": utc_iso()} if target == "opened" else {}))
        except PermissionError:
            raise HTTPException(status_code=409, detail="Invalid claim token")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"event": _public(updated)}


@router.post("/events/{event_id}/delivered")
async def delivered(event_id: str, body: ProactiveReceiptRequest, request: Request):
    return await _receipt(event_id, body, request, "delivered")


@router.post("/events/{event_id}/opened")
async def opened(event_id: str, body: ProactiveReceiptRequest, request: Request):
    return await _receipt(event_id, body, request, "opened")


@router.post("/events/{event_id}/action")
async def action(event_id: str, body: ProactiveActionRequest, request: Request):
    async with get_db() as db:
        event = await get_owned_event(db, event_id, request.state.user_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        if body.action in {"acknowledge", "complete"}:
            target = "completed"
            fields = {"completed_at_utc": utc_iso()}
        elif body.action == "dismiss":
            target = "cancelled"
            fields = {}
        elif body.action.startswith("snooze"):
            target = "snoozed"
            minutes = 10 if body.action == "snooze_10m" else 60
            fields = {"scheduled_at_utc": utc_iso(ensure_utc() + timedelta(minutes=minutes)), "claim_token": None, "claim_expires_at_utc": None}
        else:  # disable_source_type: cancel this source and future same-source pending events
            target = "cancelled"
            fields = {"last_error": "disabled_by_user"}
        try:
            updated = await record_event(db, event_id, request.state.user_id, target, claim_token=body.claim_token, **fields)
        except PermissionError:
            raise HTTPException(status_code=409, detail="Invalid claim token")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if body.action == "disable_source_type":
            await db.execute("UPDATE proactive_events SET status='cancelled', last_error='disabled_by_user', updated_at_utc=? WHERE user_id=? AND source_type=? AND status IN ('pending','snoozed')", (utc_iso(), request.state.user_id, event["source_type"]))
            await db.commit()
        if event.get("source_type") == "schedule" and target == "completed":
            await db.execute("UPDATE schedules SET status='completed', is_triggered=1, completed_at_utc=? WHERE schedule_id=? AND session_id IN (SELECT session_id FROM pet_sessions WHERE user_id=?)", (utc_iso(), event.get("source_ref_id"), request.state.user_id))
            await db.commit()
        elif event.get("source_type") == "concern":
            if target == "completed":
                await db.execute("UPDATE concern_items SET status='resolved', followup_count=followup_count+1, resolution_summary=?, updated_at_utc=? WHERE concern_id=? AND user_id=?", (body.resolution_summary, utc_iso(), event.get("source_ref_id"), request.state.user_id))
                await db.commit()
            elif target == "cancelled":
                await db.execute("UPDATE concern_items SET status='dismissed', consent_state='denied', updated_at_utc=? WHERE concern_id=? AND user_id=?", (utc_iso(), event.get("source_ref_id"), request.state.user_id))
                await db.commit()
        return {"event": _public(updated)}


@router.get("/events/recent")
async def recent(request: Request, session_id: Optional[str] = None, limit: int = 20):
    limit = max(1, min(limit, 100))
    async with get_db() as db:
        if session_id:
            cursor = await db.execute("SELECT * FROM proactive_events WHERE user_id=? AND session_id=? ORDER BY created_at_utc DESC LIMIT ?", (request.state.user_id, session_id, limit))
        else:
            cursor = await db.execute("SELECT * FROM proactive_events WHERE user_id=? ORDER BY created_at_utc DESC LIMIT ?", (request.state.user_id, limit))
        return {"events": [_public(dict(row)) for row in await cursor.fetchall()]}


@router.get("/settings")
async def get_settings(request: Request):
    async with get_db() as db:
        return await ensure_settings(db, request.state.user_id)


@router.put("/settings")
async def update_settings(body: ProactiveSettingsRequest, request: Request):
    async with get_db() as db:
        now = utc_iso()
        await ensure_settings(db, request.state.user_id, body.timezone)
        values = body.model_dump()
        values.update({"user_id": request.state.user_id, "updated_at_utc": now})
        await db.execute("""UPDATE proactive_settings SET enabled=?,timezone=?,timezone_policy=?,quiet_start=?,quiet_end=?,max_general_per_day=?,min_interval_minutes=?,schedule_enabled=?,concern_enabled=?,emotion_followup_enabled=?,inactivity_enabled=?,pet_initiated_enabled=?,privacy_level=?,updated_at_utc=? WHERE user_id=?""",
                         (int(values["enabled"]), values["timezone"], values["timezone_policy"], values["quiet_start"], values["quiet_end"], values["max_general_per_day"], values["min_interval_minutes"], int(values["schedule_enabled"]), int(values["concern_enabled"]), int(values["emotion_followup_enabled"]), int(values["inactivity_enabled"]), int(values["pet_initiated_enabled"]), values["privacy_level"], now, request.state.user_id))
        await db.commit()
        return await ensure_settings(db, request.state.user_id, body.timezone)
