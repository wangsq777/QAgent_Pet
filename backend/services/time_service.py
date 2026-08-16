"""Timezone-safe helpers used by scheduling and proactive delivery.

All values crossing the persistence boundary are UTC ISO-8601 strings.  The
helpers deliberately accept naive values for backwards compatibility, treating
them as UTC rather than silently using the host's local timezone.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def ensure_utc(value: datetime | str | None = None, *, default: datetime | None = None) -> datetime:
    if value is None:
        value = default or datetime.now(UTC)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_iso(value: datetime | str | None = None) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def get_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def localize(value: datetime | str | None, timezone_name: str) -> datetime:
    return ensure_utc(value).astimezone(get_timezone(timezone_name))


def local_date_key(value: datetime | str | None = None, timezone_name: str = "UTC") -> str:
    return localize(value, timezone_name).date().isoformat()


def local_datetime_to_utc(value: datetime, timezone_name: str) -> datetime:
    tz = get_timezone(timezone_name)
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(UTC)


def parse_quiet_time(value: str | None, fallback: time) -> time:
    try:
        hour, minute = (int(part) for part in (value or "").split(":", 1))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return time(hour, minute)
    except (ValueError, TypeError):
        pass
    return fallback


def is_quiet_hours(now: datetime, start: str, end: str, timezone_name: str) -> bool:
    current = localize(now, timezone_name).time()
    begin = parse_quiet_time(start, time(23, 0))
    finish = parse_quiet_time(end, time(8, 0))
    if begin == finish:
        return True
    if begin < finish:
        return begin <= current < finish
    return current >= begin or current < finish


def next_quiet_end(now: datetime, start: str, end: str, timezone_name: str) -> datetime:
    local_now = localize(now, timezone_name)
    finish = parse_quiet_time(end, time(8, 0))
    target = datetime.combine(local_now.date(), finish, tzinfo=get_timezone(timezone_name))
    if target <= local_now:
        target += timedelta(days=1)
    return target.astimezone(UTC)
