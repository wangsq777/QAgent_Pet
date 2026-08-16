"""Unified proactive event queue and state machine."""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from .disturbance_policy import DEFAULT_PRIORITY, decide_event
from .time_service import ensure_utc, utc_iso

STATUSES = {"pending", "claimed", "delivered", "opened", "snoozed", "completed", "cancelled", "expired", "failed"}
TRANSITIONS = {
    "pending": {"claimed", "snoozed", "cancelled", "expired", "failed"},
    "snoozed": {"pending", "claimed", "cancelled", "expired", "failed"},
    "claimed": {"delivered", "pending", "failed", "expired", "cancelled"},
    "delivered": {"opened", "completed", "snoozed", "cancelled", "expired"},
    "opened": {"completed", "snoozed", "cancelled", "expired"},
    "completed": set(), "cancelled": set(), "expired": set(), "failed": set(),
}


def _row(row) -> dict[str, Any] | None:
    return dict(row) if row else None


async def ensure_settings(db, user_id: str, timezone: str = "Asia/Shanghai") -> dict[str, Any]:
    cursor = await db.execute("SELECT * FROM proactive_settings WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    if row:
        return dict(row)
    now = utc_iso()
    await db.execute("INSERT INTO proactive_settings(user_id,timezone,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?)",
                     (user_id, timezone, now, now))
    await db.commit()
    cursor = await db.execute("SELECT * FROM proactive_settings WHERE user_id = ?", (user_id,))
    return dict(await cursor.fetchone())


async def create_event(db, *, user_id: str, session_id: str, source_type: str, scheduled_at_utc: datetime,
                       source_ref_id: str | None = None, dedupe_key: str | None = None,
                       expires_at_utc: datetime | None = None, priority: int | None = None,
                       sensitivity: str = "low", bubble_text: str = "提醒", message_context: dict | None = None,
                       rendered_message: str | None = None) -> dict[str, Any]:
    if source_type not in DEFAULT_PRIORITY:
        raise ValueError("unsupported source_type")
    event_id = str(uuid.uuid4())
    now = utc_iso()
    bubble_text = (bubble_text or "提醒").strip()[:4]
    if sensitivity in {"medium", "high"}:
        # 桌面公开层只显示低敏主题，不把情绪、地点、人名或原文泄露到气泡。
        bubble_text = "提醒" if source_type == "schedule" else "问问"
    try:
        await db.execute("""INSERT INTO proactive_events(event_id,user_id,session_id,source_type,source_ref_id,dedupe_key,scheduled_at_utc,expires_at_utc,priority,sensitivity,bubble_text,message_context_json,rendered_message,status,created_at_utc,updated_at_utc)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (event_id, user_id, session_id, source_type, source_ref_id, dedupe_key, utc_iso(scheduled_at_utc), utc_iso(expires_at_utc) if expires_at_utc else None,
                         priority if priority is not None else DEFAULT_PRIORITY[source_type], sensitivity, bubble_text,
                         json.dumps(message_context or {}, ensure_ascii=False), rendered_message, "pending", now, now))
        await db.commit()
    except Exception as exc:
        if "unique" in str(exc).lower() and dedupe_key:
            cursor = await db.execute("SELECT * FROM proactive_events WHERE dedupe_key = ?", (dedupe_key,))
            existing = await cursor.fetchone()
            if existing:
                return dict(existing)
        raise
    cursor = await db.execute("SELECT * FROM proactive_events WHERE event_id = ?", (event_id,))
    return dict(await cursor.fetchone())


async def _transition(db, event: dict[str, Any], target: str, *, now: datetime | None = None, **fields) -> dict[str, Any]:
    current = event["status"]
    if target not in TRANSITIONS.get(current, set()) and target != current:
        raise ValueError(f"invalid proactive transition: {current} -> {target}")
    now_value = utc_iso(now)
    assignments = ["status = ?", "updated_at_utc = ?"]
    values: list[Any] = [target, now_value]
    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    values.append(event["event_id"])
    await db.execute(f"UPDATE proactive_events SET {', '.join(assignments)} WHERE event_id = ?", values)
    await db.commit()
    cursor = await db.execute("SELECT * FROM proactive_events WHERE event_id = ?", (event["event_id"],))
    return dict(await cursor.fetchone())


async def claim_event(db, *, user_id: str, session_id: str, timezone: str = "Asia/Shanghai", client_id: str = "desktop",
                      now: datetime | None = None) -> dict[str, Any] | None:
    now_dt = ensure_utc(now)
    now_text = utc_iso(now_dt)
    await db.execute("BEGIN IMMEDIATE")
    try:
        await materialize_due_sources(db, user_id=user_id, session_id=session_id, now=now_dt)
        # 租约恢复与失败上限
        await db.execute("UPDATE proactive_events SET status='failed', last_error='claim_attempt_limit', claim_token=NULL, claim_expires_at_utc=NULL, updated_at_utc=? WHERE user_id=? AND session_id=? AND status='claimed' AND attempt_count >= 3 AND claim_expires_at_utc <= ?", (now_text, user_id, session_id, now_text))
        await db.execute("UPDATE proactive_events SET status='pending', claim_token=NULL, claim_expires_at_utc=NULL, updated_at_utc=? WHERE user_id=? AND session_id=? AND status='claimed' AND attempt_count < 3 AND claim_expires_at_utc <= ?", (now_text, user_id, session_id, now_text))
        await db.execute("UPDATE proactive_events SET status='expired', updated_at_utc=? WHERE user_id=? AND session_id=? AND expires_at_utc IS NOT NULL AND expires_at_utc <= ? AND status IN ('pending','snoozed')", (now_text, user_id, session_id, now_text))
        cursor = await db.execute("SELECT * FROM proactive_settings WHERE user_id = ?", (user_id,))
        settings_row = await cursor.fetchone()
        settings = dict(settings_row) if settings_row else {"enabled": 1, "timezone": timezone}
        cursor = await db.execute("SELECT * FROM proactive_events WHERE user_id=? AND session_id=? AND status IN ('pending','snoozed') AND scheduled_at_utc <= ? ORDER BY priority DESC, scheduled_at_utc ASC LIMIT 20", (user_id, session_id, now_text))
        candidates = [dict(row) for row in await cursor.fetchall()]
        recent_cursor = await db.execute("SELECT * FROM proactive_events WHERE user_id=? AND session_id=? AND delivered_at_utc IS NOT NULL ORDER BY delivered_at_utc DESC LIMIT 50", (user_id, session_id))
        recent = [dict(row) for row in await recent_cursor.fetchall()]
        selected = None
        for candidate in candidates:
            higher = any(other["priority"] > candidate["priority"] for other in candidates if other["event_id"] != candidate["event_id"])
            decision = decide_event(candidate, settings, recent, now=now_dt, higher_priority_due=higher)
            if decision.decision == "suppress":
                await db.execute("UPDATE proactive_events SET status='cancelled', last_error=?, updated_at_utc=? WHERE event_id=?", (decision.reason, now_text, candidate["event_id"]))
                continue
            if decision.decision == "snooze":
                next_at = decision.next_attempt_at_utc or utc_iso(now_dt + timedelta(minutes=15))
                await db.execute("UPDATE proactive_events SET status='pending', scheduled_at_utc=?, last_error=?, updated_at_utc=? WHERE event_id=?", (next_at, decision.reason, now_text, candidate["event_id"]))
                continue
            selected = candidate
            break
        if not selected:
            await db.commit()
            return None
        token = secrets.token_urlsafe(24)
        lease = utc_iso(now_dt + timedelta(seconds=30))
        await db.execute("UPDATE proactive_events SET status='claimed', attempt_count=attempt_count+1, claim_token=?, claim_expires_at_utc=?, updated_at_utc=? WHERE event_id=? AND status IN ('pending','snoozed')", (token, lease, now_text, selected["event_id"]))
        await db.commit()
        selected.update({"status": "claimed", "attempt_count": int(selected.get("attempt_count") or 0) + 1, "claim_token": token, "claim_expires_at_utc": lease})
        return selected
    except Exception:
        await db.rollback()
        raise


async def get_owned_event(db, event_id: str, user_id: str) -> dict[str, Any] | None:
    cursor = await db.execute("SELECT * FROM proactive_events WHERE event_id=? AND user_id=?", (event_id, user_id))
    return _row(await cursor.fetchone())


async def materialize_due_sources(db, *, user_id: str, session_id: str, now: datetime | None = None) -> int:
    """Expire drafts and materialize a conservative 24-hour inactivity event.

    Confirmed schedules/concerns create events eagerly; polling never asks an
    LLM to reinterpret chat history.
    """
    now_text = utc_iso(now)
    cursor = await db.execute(
        "UPDATE concern_items SET status='expired', updated_at_utc=? WHERE user_id=? AND session_id=? AND status='draft' AND retention_expires_at_utc IS NOT NULL AND retention_expires_at_utc <= ?",
        (now_text, user_id, session_id, now_text),
    )
    concern_count = cursor.rowcount if cursor.rowcount is not None else 0
    candidate_cursor = await db.execute("UPDATE schedule_candidates SET status='expired', updated_at_utc=? WHERE user_id=? AND session_id=? AND status='pending' AND expires_at_utc <= ?", (now_text, user_id, session_id, now_text))
    candidate_count = candidate_cursor.rowcount if candidate_cursor.rowcount is not None else 0
    materialized = 0
    cursor = await db.execute("SELECT last_interaction_at,created_at FROM pet_sessions WHERE session_id=? AND user_id=?", (session_id, user_id))
    session = await cursor.fetchone()
    cursor = await db.execute("SELECT inactivity_enabled FROM proactive_settings WHERE user_id=?", (user_id,))
    setting = await cursor.fetchone()
    if session and (setting is None or bool(setting[0])):
        last = session[0] or session[1]
        if last and ensure_utc(last) + timedelta(hours=24) <= ensure_utc(now):
            day_key = ensure_utc(now).date().isoformat()
            dedupe = f"inactivity:{session_id}:{day_key}"
            existing = await (await db.execute("SELECT event_id FROM proactive_events WHERE dedupe_key=?", (dedupe,))).fetchone()
            if not existing:
                event_id = str(uuid.uuid4())
                scheduled = ensure_utc(last) + timedelta(hours=24)
                delivery_at = max(scheduled, ensure_utc(now))
                await db.execute("""INSERT INTO proactive_events(event_id,user_id,session_id,source_type,source_ref_id,dedupe_key,scheduled_at_utc,expires_at_utc,priority,sensitivity,bubble_text,message_context_json,status,created_at_utc,updated_at_utc)
                                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (event_id, user_id, session_id, "inactivity", session_id, dedupe, utc_iso(delivery_at), utc_iso(delivery_at + timedelta(hours=2)), 30, "low", "想你", "{}", "pending", now_text, now_text))
                materialized = 1
        pet_enabled_cursor = await db.execute("SELECT pet_initiated_enabled FROM proactive_settings WHERE user_id=?", (user_id,))
        pet_setting = await pet_enabled_cursor.fetchone()
        if pet_setting is None or bool(pet_setting[0]):
            if last and ensure_utc(last) + timedelta(days=3) <= ensure_utc(now):
                bucket = int(ensure_utc(now).timestamp() // (3 * 86400))
                dedupe = f"pet_initiated:{session_id}:{bucket}"
                existing = await (await db.execute("SELECT event_id FROM proactive_events WHERE dedupe_key=?", (dedupe,))).fetchone()
                if not existing:
                    event_id = str(uuid.uuid4())
                    await db.execute("""INSERT INTO proactive_events(event_id,user_id,session_id,source_type,source_ref_id,dedupe_key,scheduled_at_utc,expires_at_utc,priority,sensitivity,bubble_text,message_context_json,status,created_at_utc,updated_at_utc)
                                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (event_id, user_id, session_id, "pet_initiated", session_id, dedupe, now_text, utc_iso(ensure_utc(now) + timedelta(hours=2)), 20, "low", "想聊", "{}", "pending", now_text, now_text))
                    materialized += 1
    return concern_count + candidate_count + materialized


async def record_event(db, event_id: str, user_id: str, target: str, *, claim_token: str | None = None,
                       now: datetime | None = None, **fields) -> dict[str, Any]:
    event = await get_owned_event(db, event_id, user_id)
    if not event:
        raise KeyError("event not found")
    if event.get("claim_token") and event.get("claim_token") != claim_token:
        raise PermissionError("invalid claim token")
    if target == "pending":
        fields.setdefault("claim_token", None)
        fields.setdefault("claim_expires_at_utc", None)
    return await _transition(db, event, target, now=now, **fields)
