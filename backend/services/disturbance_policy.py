"""Pure rules for deciding whether a proactive event may reach the desktop."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .time_service import ensure_utc, is_quiet_hours, next_quiet_end, local_date_key


DEFAULT_PRIORITY = {
    "schedule": 90, "concern": 75, "emotion_followup": 70,
    "inactivity": 30, "pet_initiated": 20,
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
    enabled_key = f"{source}_enabled"
    if not bool(settings.get("enabled", True)) or not bool(settings.get(enabled_key, True)):
        return PolicyDecision("suppress", "disabled")
    if event.get("status") in {"cancelled", "expired", "failed", "completed"}:
        return PolicyDecision("suppress", "invalid_status")
    expires = event.get("expires_at_utc")
    if expires and ensure_utc(expires) <= now:
        return PolicyDecision("suppress", "expired")
    tz = settings.get("timezone") or "UTC"
    if is_quiet_hours(now, settings.get("quiet_start", "23:00"), settings.get("quiet_end", "08:00"), tz):
        end = next_quiet_end(now, settings.get("quiet_start", "23:00"), settings.get("quiet_end", "08:00"), tz)
        return PolicyDecision("snooze", "quiet_hours", end.isoformat().replace("+00:00", "Z"))
    if source != "schedule":
        day = local_date_key(now, tz)
        general_limit = int(settings.get("max_general_per_day", 1) or 1)
        sent_today = sum(1 for item in recent_events if item.get("source_type") != "schedule" and item.get("delivered_at_utc") and local_date_key(item.get("delivered_at_utc"), tz) == day)
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
