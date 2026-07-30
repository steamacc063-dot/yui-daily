"""Timezone-safe datetime helpers for persisted Yui data."""

from __future__ import annotations

from datetime import datetime

LOCAL_TZ = datetime.now().astimezone().tzinfo


def aware_now() -> datetime:
    """Return the current local time as an offset-aware datetime."""
    return datetime.now().astimezone()


def ensure_aware(value: datetime) -> datetime:
    """Normalize a datetime to an offset-aware value in the local timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def parse_datetime(value: str | None, fallback: datetime | None = None) -> datetime:
    """Parse a persisted datetime string and normalize it to local aware time."""
    if value:
        return ensure_aware(datetime.fromisoformat(value))
    if fallback is not None:
        return ensure_aware(fallback)
    return aware_now()
