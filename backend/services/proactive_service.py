"""Unified proactive event queue and state machine."""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from .cross_pet_service import cross_pet_service
from .disturbance_policy import DEFAULT_PRIORITY, decide_event
from .llm_service import llm_service
from .time_service import ensure_utc, is_quiet_hours, local_date_key, localize, utc_iso
from .weather_service import evaluate_weather_significance, weather_service
from backend.logging_config import get_logger

logger = get_logger(__name__)

# privacy_level='generic' 时，低敏事件的气泡也统一替换为各来源的泛化词，
# 避免桌面公开层露出话题细节（如日程内容、章节名）。medium/high 的强制
# 泛化优先级更高，在 create_event 中先于本映射执行。
GENERIC_BUBBLE_BY_SOURCE = {
    "schedule": "提醒",
    "concern": "问问",
    "emotion_followup": "问问",
    "inactivity": "想你",
    "pet_initiated": "想聊",
    "sedentary": "休息",
    "hydration": "喝水",
    "sleep": "睡觉",
    "learning_nudge": "学习",
    "learning_celebrate": "真棒",
    "weather": "穿衣",
}

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
    await db.execute("INSERT INTO proactive_settings(user_id,timezone,created_at_utc,updated_at_utc) VALUES(?,?,?,?)",
                     (user_id, timezone, now, now))
    await db.commit()
    cursor = await db.execute("SELECT * FROM proactive_settings WHERE user_id = ?", (user_id,))
    return dict(await cursor.fetchone())


async def create_event(db, *, user_id: str, session_id: str, source_type: str, scheduled_at_utc: datetime,
                       source_ref_id: str | None = None, dedupe_key: str | None = None,
                       expires_at_utc: datetime | None = None, priority: int | None = None,
                       sensitivity: str = "low", bubble_text: str = "提醒", message_context: dict | None = None,
                       rendered_message: str | None = None, privacy_level: str | None = None) -> dict[str, Any]:
    if source_type not in DEFAULT_PRIORITY:
        raise ValueError("unsupported source_type")
    event_id = str(uuid.uuid4())
    now = utc_iso()
    bubble_text = (bubble_text or "提醒").strip()[:4]
    if sensitivity in {"medium", "high"}:
        # 桌面公开层只显示低敏主题，不把情绪、地点、人名或原文泄露到气泡。
        bubble_text = "提醒" if source_type == "schedule" else "问问"
    elif privacy_level is None:
        # 未显式指定时查用户设置；privacy_level='generic'（默认）把气泡泛化为各源固定词。
        try:
            cursor = await db.execute("SELECT privacy_level FROM proactive_settings WHERE user_id=?", (user_id,))
            row = await cursor.fetchone()
            privacy_level = (row[0] if row else None) or "generic"
        except Exception:
            privacy_level = "generic"
    if sensitivity == "low" and privacy_level == "generic":
        bubble_text = GENERIC_BUBBLE_BY_SOURCE.get(source_type, "提醒")
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
                      now: datetime | None = None, idle_state: dict | None = None) -> dict[str, Any] | None:
    now_dt = ensure_utc(now)
    now_text = utc_iso(now_dt)
    await db.execute("BEGIN IMMEDIATE")
    try:
        await materialize_due_sources(db, user_id=user_id, session_id=session_id, now=now_dt, idle_state=idle_state)
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


def hydration_bucket_key(local_dt: datetime) -> str:
    """hydration 去重时段键：按本地小时粗粒度防重复。"""
    return local_dt.strftime("%Y-%m-%d %H")


def iso_week_key(local_dt: datetime) -> str:
    """learning_nudge 去重周键：本地 ISO 周。"""
    year, week, _ = local_dt.isocalendar()
    return f"{year}-W{week:02d}"


async def _insert_materialized_event(db, *, user_id: str, session_id: str, source_type: str,
                                     dedupe_key: str, scheduled_at_utc: datetime, expires_at_utc: datetime,
                                     bubble_text: str, message_context: dict | None = None,
                                     rendered_message: str | None = None, source_ref_id: str | None = None,
                                     sensitivity: str = "low", now_text: str) -> bool:
    """按 dedupe_key 幂等插入物化事件。调用方须已持写锁（claim 的 BEGIN IMMEDIATE）。"""
    existing = await (await db.execute("SELECT event_id FROM proactive_events WHERE dedupe_key=?", (dedupe_key,))).fetchone()
    if existing:
        return False
    event_id = str(uuid.uuid4())
    await db.execute("""INSERT INTO proactive_events(event_id,user_id,session_id,source_type,source_ref_id,dedupe_key,scheduled_at_utc,expires_at_utc,priority,sensitivity,bubble_text,message_context_json,rendered_message,status,created_at_utc,updated_at_utc)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (event_id, user_id, session_id, source_type, source_ref_id, dedupe_key, utc_iso(scheduled_at_utc),
                      utc_iso(expires_at_utc), DEFAULT_PRIORITY[source_type], sensitivity, bubble_text,
                      json.dumps(message_context or {}, ensure_ascii=False), rendered_message, "pending", now_text, now_text))
    return True


async def _materialize_idle_sources(db, *, user_id: str, session_id: str, settings: dict[str, Any],
                                    idle_state: dict[str, Any], now: datetime) -> int:
    """桌面上报 idle_state 时物化久坐/喝水/睡觉提醒；字段缺失的源静默跳过。

    idle_state 契约（POST /api/proactive/events/claim 请求体可选字段）：
    {"idle_seconds": int, "active_streak_minutes": int}，后者为桌面统计的
    连续未空闲分钟数。整个 idle_state 缺失时本函数不被调用。
    """
    streak = idle_state.get("active_streak_minutes")
    if not isinstance(streak, (int, float)) or streak < 0:
        return 0
    streak = int(streak)
    tz = settings.get("timezone") or "Asia/Shanghai"
    local_now = localize(now, tz)
    day_key = local_now.date().isoformat()
    now_text = utc_iso(now)
    two_hours = ensure_utc(now) + timedelta(hours=2)
    materialized = 0

    # 久坐：连续活跃 >= 60 分钟，每天最多一次
    if bool(settings.get("sedentary_enabled", 1)) and streak >= 60:
        if await _insert_materialized_event(
                db, user_id=user_id, session_id=session_id, source_type="sedentary",
                dedupe_key=f"sedentary:{session_id}:{day_key}", scheduled_at_utc=now, expires_at_utc=two_hours,
                bubble_text="起来", message_context={"kind": "sedentary", "active_streak_minutes": streak},
                now_text=now_text):
            materialized += 1

    # 喝水：连续活跃 >= 45 分钟；时段键按本地小时防重，另要求近 45 分钟无 hydration 事件
    if bool(settings.get("hydration_enabled", 1)) and streak >= 45:
        recent = await (await db.execute(
            "SELECT event_id FROM proactive_events WHERE user_id=? AND session_id=? AND source_type='hydration' AND created_at_utc >= ?",
            (user_id, session_id, utc_iso(ensure_utc(now) - timedelta(minutes=45))))).fetchone()
        if not recent:
            if await _insert_materialized_event(
                    db, user_id=user_id, session_id=session_id, source_type="hydration",
                    dedupe_key=f"hydration:{session_id}:{hydration_bucket_key(local_now)}",
                    scheduled_at_utc=now, expires_at_utc=two_hours, bubble_text="喝水",
                    message_context={"kind": "hydration"}, now_text=now_text):
                materialized += 1

    # 睡觉：本地时间进入安静时段（quiet_start 未配置则跳过）且仍持续活跃 >= 15 分钟
    quiet_start = (settings.get("quiet_start") or "").strip()
    if quiet_start and bool(settings.get("sleep_enabled", 1)) and streak >= 15:
        quiet_end = (settings.get("quiet_end") or "08:00").strip()
        if is_quiet_hours(now, quiet_start, quiet_end, tz):
            if await _insert_materialized_event(
                    db, user_id=user_id, session_id=session_id, source_type="sleep",
                    dedupe_key=f"sleep:{session_id}:{day_key}", scheduled_at_utc=now, expires_at_utc=two_hours,
                    bubble_text="睡觉", message_context={"kind": "sleep"}, now_text=now_text):
                materialized += 1

    return materialized


async def _materialize_learning_nudge(db, *, user_id: str, session_id: str, settings: dict[str, Any],
                                      now: datetime) -> int:
    """学习停滞提醒：有 status='active' 的学习会话且超过 3 天未更新，每周最多一次。"""
    if not bool(settings.get("learning_enabled", 1)):
        return 0
    cursor = await db.execute(
        "SELECT updated_at FROM learning_sessions WHERE user_id=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
        (user_id,))
    row = await cursor.fetchone()
    if not row or not row[0]:
        return 0
    try:
        updated = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            # learning_sessions.updated_at 是服务器本地时间，按本地解释再转 UTC
            updated = updated.astimezone()
    except ValueError:
        return 0
    if ensure_utc(updated) + timedelta(days=3) > ensure_utc(now):
        return 0
    tz = settings.get("timezone") or "Asia/Shanghai"
    week_key = iso_week_key(localize(now, tz))
    if await _insert_materialized_event(
            db, user_id=user_id, session_id=session_id, source_type="learning_nudge",
            dedupe_key=f"learning_nudge:{user_id}:{week_key}", scheduled_at_utc=now,
            expires_at_utc=ensure_utc(now) + timedelta(hours=2), bubble_text="学习",
            message_context={"kind": "learning_nudge"}, now_text=utc_iso(now)):
        return 1
    return 0


async def _materialize_weather(db, *, user_id: str, session_id: str, settings: dict[str, Any],
                               now: datetime) -> int:
    """早晨天气主动推送：本地 08:00-09:00 窗口内，次日天气「显著」才创建，每天最多一次。

    完整人格化穿衣建议不在此预生成——桌面点按后调 POST /api/weather/outfit-advice。
    网络请求(Open-Meteo)仅在窗口内且当日未物化时发生一次。
    """
    if not bool(settings.get("weather_enabled", 1)):
        return 0
    tz = settings.get("timezone") or "Asia/Shanghai"
    local_now = localize(now, tz)
    if not (8 <= local_now.hour < 9):
        return 0
    cursor = await db.execute("SELECT region FROM user_profiles WHERE user_id=?", (user_id,))
    row = await cursor.fetchone()
    region = (row[0] or "").strip() if row else ""
    if not region:
        return 0
    day_key = local_now.date().isoformat()
    dedupe = f"weather:{user_id}:{day_key}"
    existing = await (await db.execute("SELECT event_id FROM proactive_events WHERE dedupe_key=?", (dedupe,))).fetchone()
    if existing:
        return 0
    forecast = await weather_service.get_daily_forecast(region)
    if not forecast:
        return 0
    significant, reason = evaluate_weather_significance(forecast.get("today"), forecast["tomorrow"])
    if not significant:
        return 0
    bubble = "带伞" if reason == "rain" else "穿衣"
    if await _insert_materialized_event(
            db, user_id=user_id, session_id=session_id, source_type="weather", dedupe_key=dedupe,
            scheduled_at_utc=now, expires_at_utc=ensure_utc(now) + timedelta(hours=2), bubble_text=bubble,
            message_context={"kind": "weather_outfit", "city": forecast["city"]},
            rendered_message="明天的天气有点特别，点开看看怎么穿～", now_text=utc_iso(now)):
        return 1
    return 0


async def find_pet_session_id(db, user_id: str, pet_id: str | None = None, pet_source: str | None = None) -> str | None:
    """为 proactive 事件找一个落点桌面会话：优先匹配同款宠物，否则取最近更新的会话。"""
    if pet_id:
        if pet_source == "custom":
            cursor = await db.execute(
                "SELECT session_id FROM pet_sessions WHERE user_id=? AND custom_pet_id=? ORDER BY updated_at DESC LIMIT 1",
                (user_id, pet_id))
        else:
            cursor = await db.execute(
                "SELECT session_id FROM pet_sessions WHERE user_id=? AND pet_type=? ORDER BY updated_at DESC LIMIT 1",
                (user_id, pet_id))
        row = await cursor.fetchone()
        if row:
            return row[0]
    cursor = await db.execute(
        "SELECT session_id FROM pet_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1", (user_id,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def load_pet_persona(db, user_id: str, session_id: str | None = None) -> dict[str, Any] | None:
    """读取当前宠物人格（自定义宠物 system_prompt 或预置 prompts），供文案生成。"""
    if session_id:
        cursor = await db.execute("SELECT pet_type, custom_pet_id FROM pet_sessions WHERE session_id=?", (session_id,))
        row = await cursor.fetchone()
    else:
        cursor = await db.execute(
            "SELECT pet_type, custom_pet_id FROM pet_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
            (user_id,))
        row = await cursor.fetchone()
    if not row:
        return None
    pet_key = row[1] or row[0]
    return await cross_pet_service.get_pet_persona(pet_key)


async def create_learning_celebrate_event(db, *, user_id: str, learning_session_id: str, pet_id: str,
                                          pet_source: str, chapter_id: int, chapter_title: str,
                                          now: datetime | None = None) -> dict[str, Any] | None:
    """章节完成庆祝事件：人格化文案（LLM，15s 超时兜底），失败不影响主流程。"""
    now_dt = ensure_utc(now)
    session_id = await find_pet_session_id(db, user_id, pet_id, pet_source)
    if not session_id:
        return None
    persona = await load_pet_persona(db, user_id, session_id)
    rendered = ""
    if persona and persona.get("system_prompt"):
        prompt = (
            f"主人刚刚完成了学习章节《{chapter_title}》。请用 1-2 句话庆祝主人，"
            "要符合你的性格和口头禅，真诚简短。直接输出庆祝文案，不要任何解释。"
        )
        try:
            text = await asyncio.wait_for(
                llm_service.chat(
                    [{"role": "system", "content": persona["system_prompt"]},
                     {"role": "user", "content": prompt}],
                    temperature=0.9, max_tokens=300, caller="learning_celebrate", timeout=10.0,
                ),
                timeout=15.0,
            )
            text = (text or "").strip().replace("\n", " ")
            if text and len(text) <= 120:
                rendered = text
        except Exception as exc:
            logger.warning("learning_celebrate LLM failed, fallback to template: %s", exc)
    if not rendered:
        rendered = "太棒了！又攻下一章 🎉"
    return await create_event(
        db, user_id=user_id, session_id=session_id, source_type="learning_celebrate",
        source_ref_id=learning_session_id, scheduled_at_utc=now_dt,
        expires_at_utc=now_dt + timedelta(hours=2), sensitivity="low", bubble_text="真棒",
        message_context={"kind": "learning_celebrate", "chapter_id": chapter_id, "chapter_title": chapter_title},
        rendered_message=rendered,
    )


async def materialize_due_sources(db, *, user_id: str, session_id: str, now: datetime | None = None,
                                  idle_state: dict | None = None) -> int:
    """Expire drafts and materialize a conservative 24-hour inactivity event.

    Confirmed schedules/concerns create events eagerly; polling never asks an
    LLM to reinterpret chat history. Desktop may report ``idle_state``
    (continuous active minutes) to unlock sedentary/hydration/sleep sources;
    without it those sources are silently skipped.
    """
    now_text = utc_iso(now)
    now_dt = ensure_utc(now)
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
    settings_cursor = await db.execute("SELECT * FROM proactive_settings WHERE user_id=?", (user_id,))
    settings_row = await settings_cursor.fetchone()
    settings = dict(settings_row) if settings_row else {}
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
    # Phase 3：久坐/喝水/睡觉依赖桌面 idle_state 契约，缺省静默跳过
    if idle_state and session:
        materialized += await _materialize_idle_sources(db, user_id=user_id, session_id=session_id,
                                                        settings=settings, idle_state=idle_state, now=now_dt)
    # 学习停滞提醒与早晨天气推送不依赖 idle_state，随每次 claim 物化（各自有去重与窗口）
    materialized += await _materialize_learning_nudge(db, user_id=user_id, session_id=session_id,
                                                      settings=settings, now=now_dt)
    materialized += await _materialize_weather(db, user_id=user_id, session_id=session_id,
                                               settings=settings, now=now_dt)
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
