"""Local-first task and agenda tracking backed by Markdown files."""

from __future__ import annotations

import re
from dataclasses import fields, replace
from datetime import date, datetime, time
from typing import Any

from yui import Task, _uid
from yui.obsidian.vault import ObsidianVault
from yui.productivity import VALID_PRIORITIES
from yui.time_utils import aware_now, ensure_aware, parse_datetime

STATUS_ICONS = {
    "todo": "☐",
    "in_progress": "◑",
    "done": "☑",
    "blocked": "⊘",
}

PRIORITY_ICONS = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TaskTracker:
    """Obsidian-backed personal task list and daily agenda."""

    FOLDER = "tasks"

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault

    # ── CRUD ──────────────────────────────────────────────────────────────

    def create(
        self,
        title: str,
        description: str = "",
        assignee: str = "",
        priority: str = "medium",
        tags: list[str] | None = None,
        parent_id: str = "",
        status: str = "todo",
        due_date: date | None = None,
        scheduled_time: time | None = None,
        duration_minutes: int = 30,
        area: str = "personal",
    ) -> Task:
        title = title.strip()
        self._validate_values(
            title=title,
            status=status,
            priority=priority,
            duration_minutes=duration_minutes,
        )
        task = Task(
            title=title,
            description=description,
            assignee=assignee,
            priority=priority,
            tags=tags or [],
            parent_id=parent_id,
            status=status,
            due_date=due_date,
            scheduled_time=scheduled_time,
            duration_minutes=duration_minutes,
            area=area.strip() or "personal",
            completed_at=aware_now() if status == "done" else None,
        )
        self._write(task)
        return task

    def update_status(self, task_id: str, status: str) -> Task | None:
        return self.update(
            task_id,
            status=status,
            completed_at=aware_now() if status == "done" else None,
        )

    def set_completed(self, task_id: str, *, completed: bool) -> Task | None:
        """Complete or reopen a task and persist the completion timestamp."""
        return self.update_status(task_id, "done" if completed else "todo")

    def assign(self, task_id: str, assignee: str) -> Task | None:
        return self.update(task_id, assignee=assignee)

    def update(self, task_id: str, **changes: Any) -> Task | None:
        """Return and persist an updated copy of a task."""
        task = self.get(task_id)
        if task is None:
            return None

        allowed = {field.name for field in fields(Task)} - {"id", "created", "updated"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported task fields: {', '.join(sorted(unknown))}")

        normalized = dict(changes)
        if "title" in normalized:
            normalized["title"] = str(normalized["title"]).strip()
        if "area" in normalized:
            normalized["area"] = str(normalized["area"]).strip() or "personal"
        self._validate_values(
            title=normalized.get("title", task.title),
            status=normalized.get("status", task.status),
            priority=normalized.get("priority", task.priority),
            duration_minutes=normalized.get("duration_minutes", task.duration_minutes),
        )
        if "completed_at" in normalized and normalized["completed_at"] is not None:
            normalized["completed_at"] = ensure_aware(normalized["completed_at"])

        updated = replace(task, **normalized, updated=aware_now())
        self._write(updated)
        return updated

    def delete(self, task_id: str) -> bool:
        self._validate_task_id(task_id)
        return self.vault.delete_note(f"{self.FOLDER}/{task_id}.md")

    # ── Queries ───────────────────────────────────────────────────────────

    def get(self, task_id: str) -> Task | None:
        self._validate_task_id(task_id)
        fm, body = self.vault.read_note(f"{self.FOLDER}/{task_id}.md")
        if not fm:
            return None
        try:
            return self._from_fm(fm, body)
        except (TypeError, ValueError):
            return None

    def list_all(self, status: str | None = None, assignee: str | None = None) -> list[Task]:
        tasks: list[Task] = []
        for note in self.vault.list_notes(self.FOLDER):
            fm, body = self.vault.read_note(note)
            if not fm:
                continue
            if status and fm.get("status") != status:
                continue
            if assignee and fm.get("assignee") != assignee:
                continue
            try:
                tasks.append(self._from_fm(fm, body))
            except (TypeError, ValueError):
                continue
        tasks.sort(key=lambda t: t.created, reverse=True)
        return tasks

    def board(self) -> dict[str, list[Task]]:
        """Return tasks grouped by status — kanban view."""
        groups: dict[str, list[Task]] = {
            "todo": [],
            "in_progress": [],
            "done": [],
            "blocked": [],
        }
        for task in self.list_all():
            groups.setdefault(task.status, []).append(task)
        return groups

    def agenda(self, day: date, *, include_overdue: bool = False) -> list[Task]:
        """Return tasks for a day, optionally prefixed with unfinished overdue work."""
        tasks = []
        for task in self.list_all():
            is_overdue = bool(task.due_date and task.due_date < day and task.status != "done")
            if task.due_date == day or (include_overdue and is_overdue):
                tasks.append(task)

        def agenda_key(task: Task) -> tuple:
            overdue_rank = 0 if task.due_date and task.due_date < day else 1
            done_rank = 1 if task.status == "done" else 0
            unscheduled_rank = 1 if task.scheduled_time is None else 0
            clock = task.scheduled_time or time.max
            priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            return (
                overdue_rank,
                done_rank,
                unscheduled_rank,
                clock,
                priority_rank.get(task.priority, 2),
                task.created,
            )

        return sorted(tasks, key=agenda_key)

    def inbox(self) -> list[Task]:
        """Return unfinished tasks that have not been placed on a day."""
        return [task for task in self.list_all() if task.due_date is None and task.status != "done"]

    def upcoming(self, after: date, *, days: int = 14) -> list[Task]:
        """Return unfinished tasks after a day within a bounded horizon."""
        horizon = after.toordinal() + days
        tasks = [
            task
            for task in self.list_all()
            if task.due_date
            and after < task.due_date
            and task.due_date.toordinal() <= horizon
            and task.status != "done"
        ]
        return sorted(tasks, key=lambda task: (task.due_date, task.scheduled_time or time.max))

    def completed(self) -> list[Task]:
        """Return completed tasks, newest completion first."""
        tasks = [task for task in self.list_all(status="done")]
        return sorted(
            tasks,
            key=lambda task: task.completed_at or task.updated,
            reverse=True,
        )

    def daily_summary(self, day: date) -> dict[str, int]:
        """Calculate the compact progress metrics shown in the right panel."""
        return self.summarize(self.agenda(day))

    @staticmethod
    def summarize(tasks: list[Task]) -> dict[str, int]:
        """Summarize exactly the tasks visible in a view."""
        completed = sum(task.status == "done" for task in tasks)
        total = len(tasks)
        return {
            "total": total,
            "completed": completed,
            "remaining": total - completed,
            "planned_minutes": sum(task.duration_minutes for task in tasks),
            "completion_percent": round((completed / total) * 100) if total else 0,
        }

    def stats(self) -> dict[str, int]:
        board = self.board()
        return {k: len(v) for k, v in board.items()}

    # ── Rendering ─────────────────────────────────────────────────────────

    @staticmethod
    def _render_body(task: Task) -> str:
        icon = STATUS_ICONS.get(task.status, "☐")
        pri = PRIORITY_ICONS.get(task.priority, "🟡")
        lines = [
            f"# {icon} {task.title}",
            "",
            f"**Priority:** {pri} {task.priority}",
            f"**Area:** {task.area}",
            f"**Status:** {task.status}",
            f"**When:** {TaskTracker._format_when(task)}",
            f"**Duration:** {task.duration_minutes} minutes",
            "",
        ]
        if task.description:
            lines += ["## Description", "", task.description, ""]
        if task.tags:
            lines.append("**Tags:** " + " ".join(f"#{t}" for t in task.tags))
        return "\n".join(lines)

    # ── Conversion ────────────────────────────────────────────────────────

    @staticmethod
    def _to_fm(task: Task) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "assignee": task.assignee,
            "tags": task.tags,
            "parent_id": task.parent_id,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "scheduled_time": (
                task.scheduled_time.isoformat(timespec="minutes")
                if task.scheduled_time
                else None
            ),
            "duration_minutes": task.duration_minutes,
            "area": task.area,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created": task.created.isoformat(),
            "updated": task.updated.isoformat(),
        }

    @staticmethod
    def _from_fm(fm: dict, body: str) -> Task:
        task_id = str(fm.get("id", _uid()))
        TaskTracker._validate_task_id(task_id)
        return Task(
            id=task_id,
            title=fm.get("title", "Untitled"),
            description=TaskTracker._extract_description(body),
            status=fm.get("status", "todo"),
            priority=fm.get("priority", "medium"),
            assignee=fm.get("assignee", ""),
            tags=fm.get("tags", []),
            parent_id=fm.get("parent_id", ""),
            due_date=TaskTracker._parse_date(fm.get("due_date")),
            scheduled_time=TaskTracker._parse_time(fm.get("scheduled_time")),
            duration_minutes=int(fm.get("duration_minutes", 30)),
            area=fm.get("area", "personal"),
            completed_at=(
                parse_datetime(fm.get("completed_at"))
                if fm.get("completed_at")
                else None
            ),
            created=parse_datetime(fm.get("created")),
            updated=parse_datetime(fm.get("updated", fm.get("created"))),
        )

    def _write(self, task: Task) -> None:
        self.vault.write_note(
            f"{self.FOLDER}/{task.id}.md",
            self._render_body(task),
            frontmatter=self._to_fm(task),
        )

    @staticmethod
    def _validate_values(
        *,
        title: str,
        status: str,
        priority: str,
        duration_minutes: int,
    ) -> None:
        if not title:
            raise ValueError("Task title cannot be empty.")
        if status not in STATUS_ICONS:
            raise ValueError(f"Invalid status: {status}")
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {priority}")
        if not isinstance(duration_minutes, int) or not 1 <= duration_minutes <= 1440:
            raise ValueError("Duration must be between 1 and 1440 minutes.")

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if not _SAFE_TASK_ID.fullmatch(str(task_id)):
            raise ValueError("Invalid task id; expected a safe local identifier.")

    @staticmethod
    def _parse_date(value: str | date | None) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    @staticmethod
    def _parse_time(value: str | time | None) -> time | None:
        if value is None or value == "":
            return None
        if isinstance(value, time):
            return value
        return time.fromisoformat(str(value))

    @staticmethod
    def _format_when(task: Task) -> str:
        if not task.due_date:
            return "Inbox"
        label = task.due_date.isoformat()
        if task.scheduled_time:
            label += f" at {task.scheduled_time.strftime('%H:%M')}"
        return label

    @staticmethod
    def _extract_description(body: str) -> str:
        """Extract the description section from a rendered task note body."""
        marker = "\n## Description\n\n"
        if marker not in body:
            current_markers = ("**Priority:**", "**Status:**", "**When:**", "**Duration:**")
            legacy_markers = ("**Priority:**", "**Assignee:**", "**Status:**")
            if all(value in body for value in current_markers) or all(
                value in body for value in legacy_markers
            ):
                return ""
            return body.strip()

        description = body.split(marker, 1)[1]
        tags_marker = "\n**Tags:** "
        if tags_marker in description:
            description = description.split(tags_marker, 1)[0]
        return description.strip()
