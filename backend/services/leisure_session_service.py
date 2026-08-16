from __future__ import annotations

import uuid
from datetime import datetime

from .module_registry import validate_module
from .time_service import ensure_utc, utc_iso


async def open_session(db, *, user_id: str, module_id: str, content_ref_id: str | None = None) -> dict:
    module = validate_module(module_id)
    cursor = await db.execute("SELECT * FROM leisure_sessions WHERE user_id=? AND status='active'", (user_id,))
    existing = await cursor.fetchone()
    if existing:
        if existing["module_id"] == module_id and existing["content_ref_id"] == content_ref_id:
            return dict(existing)
        await close_session(db, user_id=user_id, session_id=existing["session_id"], reason="switch_module")
    now = utc_iso()
    session_id = str(uuid.uuid4())
    await db.execute("""INSERT INTO leisure_sessions(session_id,user_id,module_id,content_ref_id,status,started_at_utc,last_resumed_at_utc,created_at_utc,updated_at_utc)
                      VALUES(?,?,?,?,?,?,?,?,?)""", (session_id, user_id, module["module_id"], content_ref_id, "active", now, now, now, now))
    await db.commit()
    cursor = await db.execute("SELECT * FROM leisure_sessions WHERE session_id=?", (session_id,))
    return dict(await cursor.fetchone())


async def _get_owned(db, user_id: str, session_id: str):
    cursor = await db.execute("SELECT * FROM leisure_sessions WHERE session_id=? AND user_id=?", (session_id, user_id))
    return await cursor.fetchone()


async def pause_session(db, *, user_id: str, session_id: str) -> dict:
    row = await _get_owned(db, user_id, session_id)
    if not row:
        raise KeyError("session not found")
    if row["status"] != "active":
        return dict(row)
    now = ensure_utc()
    last = ensure_utc(row["last_resumed_at_utc"] or row["started_at_utc"])
    elapsed = max(0, int((now - last).total_seconds()))
    await db.execute("UPDATE leisure_sessions SET status='paused',paused_at_utc=?,accumulated_seconds=accumulated_seconds+?,updated_at_utc=? WHERE session_id=? AND user_id=?", (utc_iso(now), elapsed, utc_iso(now), session_id, user_id))
    await db.commit()
    cursor = await db.execute("SELECT * FROM leisure_sessions WHERE session_id=?", (session_id,))
    return dict(await cursor.fetchone())


async def resume_session(db, *, user_id: str, session_id: str) -> dict:
    row = await _get_owned(db, user_id, session_id)
    if not row:
        raise KeyError("session not found")
    if row["status"] == "active":
        return dict(row)
    if row["status"] == "closed":
        raise ValueError("closed session cannot resume")
    now = utc_iso()
    await db.execute("UPDATE leisure_sessions SET status='active',last_resumed_at_utc=?,updated_at_utc=? WHERE session_id=? AND user_id=?", (now, now, session_id, user_id))
    await db.commit()
    cursor = await db.execute("SELECT * FROM leisure_sessions WHERE session_id=?", (session_id,))
    return dict(await cursor.fetchone())


async def close_session(db, *, user_id: str, session_id: str, reason: str = "user_exit") -> dict:
    row = await _get_owned(db, user_id, session_id)
    if not row:
        raise KeyError("session not found")
    if row["status"] == "closed":
        return dict(row)
    now = ensure_utc()
    accumulated = int(row["accumulated_seconds"] or 0)
    if row["status"] == "active":
        accumulated += max(0, int((now - ensure_utc(row["last_resumed_at_utc"] or row["started_at_utc"])).total_seconds()))
    await db.execute("UPDATE leisure_sessions SET status='closed',closed_at_utc=?,accumulated_seconds=?,close_reason=?,updated_at_utc=? WHERE session_id=? AND user_id=?", (utc_iso(now), accumulated, reason[:50], utc_iso(now), session_id, user_id))
    await db.commit()
    cursor = await db.execute("SELECT * FROM leisure_sessions WHERE session_id=?", (session_id,))
    return dict(await cursor.fetchone())
