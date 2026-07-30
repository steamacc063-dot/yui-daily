"""Small, predictable helpers for Yui's productivity workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta

VALID_PRIORITIES = frozenset({"low", "medium", "high", "critical"})

_TIME_TOKEN = re.compile(r"(?<!\S)@(\d{1,2}):(\d{2})(?!\S)")
_DURATION_TOKEN = re.compile(r"(?<!\S)/(\d{1,3})m(?!\S)", re.IGNORECASE)
_AREA_TOKEN = re.compile(r"(?<!\S)#([\w-]+)(?!\S)")
_PRIORITY_TOKEN = re.compile(
    r"(?<!\S)!(low|medium|high|critical)(?!\S)",
    re.IGNORECASE,
)
_DATE_TOKEN = re.compile(r"(?<!\S)~(\d{4}-\d{2}-\d{2})(?!\S)")
_RELATIVE_DATE_TOKEN = re.compile(r"(?<!\S)(today|tomorrow)(?!\S)", re.IGNORECASE)


@dataclass(frozen=True)
class TaskDraft:
    """Validated values produced by the quick-capture parser."""

    title: str
    due_date: date
    scheduled_time: time | None = None
    duration_minutes: int = 30
    area: str = "personal"
    priority: str = "medium"
    date_was_explicit: bool = False


def parse_quick_task(text: str, *, default_date: date) -> TaskDraft:
    """Parse terminal-friendly task metadata without changing normal title words.

    Supported tokens are ``@HH:MM``, ``/30m``, ``#area``, ``!priority``,
    ``today``, ``tomorrow``, and ``~YYYY-MM-DD``. Unknown text remains part of
    the title so capture never feels fragile.
    """
    raw = text.strip()
    if not raw:
        raise ValueError("Task title cannot be empty.")

    scheduled_time: time | None = None
    time_match = _TIME_TOKEN.search(raw)
    if time_match:
        hour, minute = (int(value) for value in time_match.groups())
        try:
            scheduled_time = time(hour, minute)
        except ValueError as exc:
            raise ValueError("Time must use a valid 24-hour HH:MM value.") from exc
        raw = _TIME_TOKEN.sub(" ", raw, count=1)

    duration_minutes = 30
    duration_match = _DURATION_TOKEN.search(raw)
    if duration_match:
        duration_minutes = int(duration_match.group(1))
        if duration_minutes < 1:
            raise ValueError("Duration must be at least one minute.")
        raw = _DURATION_TOKEN.sub(" ", raw, count=1)

    area = "personal"
    area_match = _AREA_TOKEN.search(raw)
    if area_match:
        area = area_match.group(1).lower()
        raw = _AREA_TOKEN.sub(" ", raw, count=1)

    priority = "medium"
    priority_match = _PRIORITY_TOKEN.search(raw)
    if priority_match:
        priority = priority_match.group(1).lower()
        raw = _PRIORITY_TOKEN.sub(" ", raw, count=1)

    due_date = default_date
    date_was_explicit = False
    explicit_date_match = _DATE_TOKEN.search(raw)
    relative_date_match = _RELATIVE_DATE_TOKEN.search(raw)
    if explicit_date_match:
        date_was_explicit = True
        try:
            due_date = date.fromisoformat(explicit_date_match.group(1))
        except ValueError as exc:
            raise ValueError("Date must use a valid YYYY-MM-DD value.") from exc
        raw = _DATE_TOKEN.sub(" ", raw, count=1)
    elif relative_date_match:
        date_was_explicit = True
        if relative_date_match.group(1).lower() == "tomorrow":
            due_date = default_date + timedelta(days=1)
        raw = _RELATIVE_DATE_TOKEN.sub(" ", raw, count=1)

    title = " ".join(raw.split())
    if not title:
        raise ValueError("Task title cannot be empty.")

    return TaskDraft(
        title=title,
        due_date=due_date,
        scheduled_time=scheduled_time,
        duration_minutes=duration_minutes,
        area=area,
        priority=priority,
        date_was_explicit=date_was_explicit,
    )
