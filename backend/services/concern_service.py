"""User-controlled 'things to remember' lifecycle."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from .proactive_service import create_event
from .time_service import ensure_utc, utc_iso


async def create_concern(db, *, user_id: str, session_id: str, kind: str, subject: str, summary: str = "",
                         sensitivity: str = "low", consent_state: str = "pending",
                         next_followup_at_utc: datetime | None = None, max_followups: int = 1,
                         source_message_id: str | None = None) -> dict[str, Any]:
    now = ensure_utc()
    concern_id = str(uuid.uuid4())
    status = "active" if consent_state in {"explicit", "confirmed"} else "draft"
    retention = now + timedelta(hours=72) if status == "draft" else None
    await db.execute("""INSERT INTO concern_items(concern_id,user_id,session_id,kind,subject,summary,source_message_id,sensitivity,consent_state,status,next_followup_at_utc,followup_count,max_followups,retention_expires_at_utc,created_at_utc,updated_at_utc)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (concern_id, user_id, session_id, kind, subject[:120], summary[:500], source_message_id, sensitivity, consent_state, status,
                      utc_iso(next_followup_at_utc) if next_followup_at_utc else None, 0, max_followups, utc_iso(retention) if retention else None, utc_iso(now), utc_iso(now)))
    if status == "active" and next_followup_at_utc:
        await create_event(db, user_id=user_id, session_id=session_id, source_type="concern", source_ref_id=concern_id,
                           dedupe_key=f"concern:{concern_id}:followup:0", scheduled_at_utc=next_followup_at_utc,
                           expires_at_utc=ensure_utc(next_followup_at_utc) + timedelta(hours=48), priority=75,
                           sensitivity=sensitivity, bubble_text="问问", message_context={"subject": subject[:120]})
    await db.commit()
    cursor = await db.execute("SELECT * FROM concern_items WHERE concern_id=?", (concern_id,))
    return dict(await cursor.fetchone())


async def confirm_concern(db, concern: dict[str, Any], *, next_followup_at_utc: datetime | None = None) -> dict[str, Any]:
    when = next_followup_at_utc or (ensure_utc(concern.get("next_followup_at_utc")) if concern.get("next_followup_at_utc") else ensure_utc() + timedelta(hours=24))
    now = utc_iso()
    await db.execute("UPDATE concern_items SET consent_state='confirmed', status='active', next_followup_at_utc=?, retention_expires_at_utc=NULL, updated_at_utc=? WHERE concern_id=?", (utc_iso(when), now, concern["concern_id"]))
    await create_event(db, user_id=concern["user_id"], session_id=concern["session_id"], source_type="concern", source_ref_id=concern["concern_id"], dedupe_key=f"concern:{concern['concern_id']}:followup:0", scheduled_at_utc=when, expires_at_utc=when + timedelta(hours=48), priority=75, sensitivity=concern.get("sensitivity", "low"), bubble_text="问问", message_context={"subject": concern["subject"]})
    await db.commit()
    cursor = await db.execute("SELECT * FROM concern_items WHERE concern_id=?", (concern["concern_id"],))
    return dict(await cursor.fetchone())
