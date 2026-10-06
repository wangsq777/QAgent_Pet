"""Pure rules for deciding whether a proactive event may reach the desktop."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .time_service import ensure_utc, is_quiet_hours, next_quiet_end, local_date_key


DEFAULT_PRIORITY = {
    "schedule": 90, "concern": 75, "emotion_followup": 70,
    "inactivity": 30, "pet_initiated": 20,
    "sedentary": 15, "hydration": 10, "sleep": 18,
    "learning_nudge": 20, "learning_celebrate": 20, "weather": 25,
}

# 部分来源共用一个用户开关：学习停滞提醒与章节完成庆祝都归 learning_enabled 管
# （settings 列名是 learning_enabled，而非 f"{source}_enabled"）。
SOURCE_ENABLED_SETTING_KEY = {
    "learning_nudge": "learning_enabled",
    "learning_celebrate": "learning_enabled",
}


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    reason: str
    next_attempt_at_utc: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "reason": self.reason,
                "next_attempt_at_utc": self.next_attempt_at_utc}


def decide_event(event: dict[str, Any], settings: dict[str, Any], recent_events: list[dict[str, Any]] | None = None,
                 *, now: datetime | None = None, has_active_display: bool = False,
                 higher_priority_due: bool = False) -> PolicyDecision:
    now = ensure_utc(now)
    recent_events = recent_events or []
    source = event.get("source_type", "")
    enabled_key = SOURCE_ENABLED_SETTING_KEY.get(source, f"{source}_enabled")
    if not bool(settings.get("enabled", True)) or not bool(settings.get(enabled_key, True)):
        return PolicyDecision("suppress", "disabled")
    if event.get("status") in {"cancelled", "expired", "failed", "completed"}:
        return PolicyDecision("suppress", "invalid_status")
    expires = event.get("expires_at_utc")
    if expires and ensure_utc(expires) <= now:
        return PolicyDecision("suppress", "expired")
    tz = settings.get("timezone") or "UTC"
    # sleep 提醒只在安静时段（默认 23:00-08:00）物化，本来就是为安静时段服务的：
    # 若仍按 quiet hours snooze，+2h 后事件必然过期，等于永不送达，因此豁免该层压制。
    # 每日上限、min_interval 与 sleep_enabled 开关仍照常约束；
    # dnd 静默由桌面端 claim 前拦截保证，不受影响。
    if source != "sleep" and is_quiet_hours(now, settings.get("quiet_start", "23:00"), settings.get("quiet_end", "08:00"), tz):
        end = next_quiet_end(now, settings.get("quiet_start", "23:00"), settings.get("quiet_end", "08:00"), tz)
        return PolicyDecision("snooze", "quiet_hours", end.isoformat().replace("+00:00", "Z"))
    if source != "schedule":
        day = local_date_key(now, tz)
        general_limit = int(settings.get("max_general_per_day", 1) or 1)
        # 每日上限按「来源」独立计数：默认上限 1 = 每个来源每天最多打扰一次。
        # 全局仍受 quiet hours 与 min_interval_minutes 约束，多来源之间不会互相饿死；
        # 若旧口径按全源共用 1 条，久坐/喝水等新源将永远无法触达用户。
        sent_today = sum(1 for item in recent_events if item.get("source_type") == source and item.get("delivered_at_utc") and local_date_key(item.get("delivered_at_utc"), tz) == day)
        if sent_today >= general_limit:
            return PolicyDecision("snooze", "daily_limit", None)
        interval = int(settings.get("min_interval_minutes", 120) or 120)
        delivered = [ensure_utc(item["delivered_at_utc"]) for item in recent_events if item.get("delivered_at_utc")]
        if delivered and now - max(delivered) < timedelta(minutes=interval):
            return PolicyDecision("snooze", "rate_limit", (max(delivered) + timedelta(minutes=interval)).isoformat().replace("+00:00", "Z"))
    if event.get("consecutive_ignored", 0) >= 2 and source == "inactivity":
        return PolicyDecision("suppress", "ignored_limit")
    if higher_priority_due:
        return PolicyDecision("snooze", "lower_priority", None)
    if has_active_display:
        return PolicyDecision("snooze", "active_display", None)
    return PolicyDecision("deliver", "eligible")
