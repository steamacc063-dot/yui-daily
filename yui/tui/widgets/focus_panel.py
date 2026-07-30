"""Selected-task inspector and daily progress panel."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from yui import Task


class FocusPanel(Widget):
    """Right rail showing progress and the currently selected task."""

    def compose(self) -> ComposeResult:
        yield Static("DAILY PULSE", classes="panel-label")
        yield Static("░░░░░░░░░░  0%", id="progress-bar")
        yield Static("0 of 0 complete", id="progress-copy")
        yield Static("0m planned", id="planned-time")
        yield Static("ON DECK", classes="panel-label detail-label")
        yield Static("Choose a task from the agenda.", id="task-title")
        yield Static("", id="task-meta")
        yield Static("", id="task-notes")
        yield Static(
            "[b]SPACE[/b] · COMPLETE\n"
            "[b]P[/b]     · PRIORITY\n"
            "[b]M[/b]     · TOMORROW\n"
            "[b]E[/b]     · EDIT TASK\n"
            "[b]N[/b]     · NEW TASK",
            id="action-legend",
        )

    def update_summary(self, summary: dict[str, int]) -> None:
        percent = summary.get("completion_percent", 0)
        filled = min(10, max(0, round(percent / 10)))
        bar = "█" * filled + "░" * (10 - filled)
        self.query_one("#progress-bar", Static).update(f"{bar}  {percent}%")
        self.query_one("#progress-copy", Static).update(
            f"{summary.get('completed', 0)} of {summary.get('total', 0)} complete"
        )
        minutes = summary.get("planned_minutes", 0)
        hours, remainder = divmod(minutes, 60)
        time_copy = f"{hours}h {remainder:02d}m" if hours else f"{remainder}m"
        self.query_one("#planned-time", Static).update(f"{time_copy} planned")

    def update_task(self, task: Task | None) -> None:
        if task is None:
            self.query_one("#task-title", Static).update("Choose a task from the agenda.")
            self.query_one("#task-meta", Static).update("")
            self.query_one("#task-notes", Static).update("")
            return

        title = escape(task.title)
        date_label = task.due_date.strftime("%a, %b %d") if task.due_date else "Inbox"
        time_label = task.scheduled_time.strftime("%H:%M") if task.scheduled_time else "Anytime"
        self.query_one("#task-title", Static).update(title)
        self.query_one("#task-meta", Static).update(
            f"[#d6a85f]{date_label} · {time_label}[/]\n"
            f"{task.duration_minutes} minutes  ·  {escape(task.area.upper())}\n"
            f"{task.priority.upper()} PRIORITY"
        )
        notes = escape(task.description) if task.description else "No notes — keep it light."
        self.query_one("#task-notes", Static).update(notes)
