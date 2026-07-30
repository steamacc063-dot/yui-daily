"""Yui (結) — a local-first daily agenda and task system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Callable, Coroutine

from yui.time_utils import aware_now

__version__ = "1.0.0"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ── Shared Types ──────────────────────────────────────────────────────────────


@dataclass
class Message:
    """A message exchanged on the internal bus."""

    sender: str
    content: str
    channel: str = "general"
    receiver: str = "all"
    msg_type: str = "chat"  # chat | system | task | memory | command
    id: str = field(default_factory=_uid)
    timestamp: datetime = field(default_factory=aware_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentIdentity:
    """Parsed from an identity.md file."""

    id: str
    name: str
    role: str
    persona: str = ""
    skills: list[str] = field(default_factory=list)
    system_prompt: str = ""
    avatar: str = "●"
    color: str = "#6c63ff"


@dataclass
class Task:
    """A personal task stored as a plain Markdown note."""

    title: str
    description: str = ""
    status: str = "todo"  # todo | in_progress | done | blocked
    assignee: str = ""
    priority: str = "medium"  # low | medium | high | critical
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=_uid)
    created: datetime = field(default_factory=aware_now)
    updated: datetime = field(default_factory=aware_now)
    parent_id: str = ""
    due_date: date | None = None
    scheduled_time: time | None = None
    duration_minutes: int = 30
    area: str = "personal"
    completed_at: datetime | None = None


@dataclass
class MemoryEntry:
    """A single memory unit (Mem0-style)."""

    content: str
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    id: str = field(default_factory=_uid)
    created: datetime = field(default_factory=aware_now)
    accessed: datetime = field(default_factory=aware_now)
    access_count: int = 0
    source: str = ""


@dataclass
class SearchResult:
    """A result returned by vault search."""

    path: str
    score: float
    snippet: str
    title: str = ""


# Type alias for async event handlers
AsyncHandler = Callable[..., Coroutine[Any, Any, None]]
