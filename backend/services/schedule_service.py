"""Schedule parsing and persistence helpers."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from .time_service import UTC, ensure_utc, get_timezone, local_datetime_to_utc, utc_iso

_TIME_RE = re.compile(r"(?P<hour>\d{1,2})(?:点|时)(?:(?P<minute>\d{1,2})分?)?")
_CN_TIME_RE = re.compile(r"(?P<hour>[一二三四五六七八九十两]{1,3})点(?:(?P<minute>[一二三四五六七八九十两]{1,3})分?)?")
_REL_RE = re.compile(r"(?P<num>\d+)\s*(?P<unit>分钟|分|小时|钟|天)后")
_CN_REL_RE = re.compile(r"(?P<num>半|一|两|二|三|四|五|六|七|八|九|十)\s*(?P<unit>分钟|分|小时|钟|天)后")
_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _cn_number(value: str) -> int:
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十": return 10
    if value.startswith("十"): return 10 + digits.get(value[1:], 0)
    if value.endswith("十"): return digits.get(value[0], 1) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, 0)


def parse_schedule_candidate(text: str, *, now_local: datetime, timezone: str) -> dict[str, Any]:
    """Parse common Chinese relative/absolute expressions without an LLM.

    A result with ``needs_confirmation`` is safe to show to the user but must
    not be inserted into the formal schedule table until confirmed.
    """
    content = re.sub(r"^\s*(?:提醒我|记得提醒我|帮我记得)\s*", "", text).strip()
    local_now = now_local.astimezone(get_timezone(timezone)) if now_local.tzinfo else now_local.replace(tzinfo=get_timezone(timezone))
    target = None
    match = _REL_RE.search(text) or _CN_REL_RE.search(text)
    if match:
        amount = 0.5 if match.group("num") == "半" else _cn_number(match.group("num"))
        unit = match.group("unit")
        target = local_now + timedelta(minutes=amount if unit in {"分钟", "分"} else amount * 60 if unit in {"小时", "钟"} else amount * 1440)
    else:
        day = local_now.date()
        if "明天" in text:
            day += timedelta(days=1)
        elif "后天" in text:
            day += timedelta(days=2)
        elif "今天" in text:
            pass
        elif (weekday_match := re.search(r"下周([一二三四五六日天])", text)):
            desired = _WEEKDAY[weekday_match.group(1)]
            day += timedelta(days=(7 - local_now.weekday()) + desired)
        elif (weekday_match := re.search(r"周([一二三四五六日天])", text)):
            desired = _WEEKDAY[weekday_match.group(1)]
            day += timedelta(days=(desired - local_now.weekday()) % 7)
        time_match = _TIME_RE.search(text)
        is_cn_time = False
        if not time_match:
            time_match = _CN_TIME_RE.search(text)
            is_cn_time = bool(time_match)
        if time_match:
            hour = _cn_number(time_match.group("hour")) if is_cn_time else int(time_match.group("hour"))
            minute = _cn_number(time_match.group("minute")) if is_cn_time and time_match.group("minute") else int(time_match.group("minute") or 0)
            if "下午" in text or "晚上" in text:
                if 1 <= hour < 12: hour += 12
            if hour < 24 and minute < 60:
                target = local_now.replace(year=day.year, month=day.month, day=day.day, hour=hour, minute=minute, second=0, microsecond=0)
    explicit = bool(re.search(r"提醒|记得|闹钟|到点", text))
    reason = None
    if target is None:
        reason = "missing_time"
    elif target <= local_now:
        reason = "past_time"
    elif not explicit:
        reason = "inferred_intent"
    confidence = 0.95 if target and explicit and not reason else 0.55 if target else 0.15
    return {
        "content": content or text[:200],
        "scheduled_at_local": target.isoformat() if target else None,
        "scheduled_at_utc": utc_iso(local_datetime_to_utc(target, timezone)) if target and not reason else None,
        "timezone": timezone,
        "confidence": confidence,
        "needs_confirmation": bool(reason),
        "ambiguity_reason": reason,
    }


def normalize_schedule_time(*, scheduled_at: datetime | None, scheduled_at_utc: datetime | None, timezone: str) -> datetime:
    if scheduled_at_utc is not None:
        return ensure_utc(scheduled_at_utc)
    if scheduled_at is None:
        raise ValueError("scheduled_at is required")
    return local_datetime_to_utc(scheduled_at, timezone)


async def create_schedule(db, *, user_id: str, session_id: str, content: str, scheduled_at_utc: datetime,
                          timezone: str = "Asia/Shanghai", reminder_offset_minutes: int = 0,
                          origin: str = "manual", source_message_id: str | None = None,
                          schedule_id: str | None = None) -> dict[str, Any]:
    now = utc_iso()
    schedule_id = schedule_id or str(uuid.uuid4())
    trigger_at = ensure_utc(scheduled_at_utc) - timedelta(minutes=reminder_offset_minutes)
    await db.execute(
        """INSERT INTO schedules(schedule_id,session_id,content,scheduled_time,is_triggered,created_at,scheduled_at_utc,timezone,status,reminder_offset_minutes,origin,source_message_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (schedule_id, session_id, content, utc_iso(scheduled_at_utc), 0, now, utc_iso(scheduled_at_utc), timezone, "pending", reminder_offset_minutes, origin, source_message_id),
    )
    from .proactive_service import create_event
    await create_event(db, user_id=user_id, session_id=session_id, source_type="schedule", source_ref_id=schedule_id,
                       dedupe_key=f"schedule:{schedule_id}:primary", scheduled_at_utc=trigger_at,
                       expires_at_utc=ensure_utc(scheduled_at_utc) + timedelta(hours=2), priority=90,
                       sensitivity="low", bubble_text="提醒", message_context={"content": content})
    return {"schedule_id": schedule_id, "session_id": session_id, "content": content,
            "scheduled_at_utc": utc_iso(scheduled_at_utc), "timezone": timezone, "status": "pending"}
