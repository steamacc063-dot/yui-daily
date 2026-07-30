"""Task editing and destructive-action confirmation screens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from yui import Task
from yui.productivity import VALID_PRIORITIES


@dataclass(frozen=True)
class TaskEdit:
    """Validated edit values returned to the application."""

    task_id: str
    changes: dict[str, object]


class TaskEditorScreen(ModalScreen[TaskEdit | None]):
    """A focused editor for the metadata quick capture cannot comfortably change."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, task: Task) -> None:
        super().__init__()
        self.edited_task = task

    def compose(self) -> ComposeResult:
        with Vertical(id="editor-dialog"):
            yield Static("EDIT TASK", classes="modal-kicker")
            yield Static("Shape the work, then return to the day.", classes="modal-copy")
            yield Static("TITLE", classes="field-label")
            yield Input(value=self.edited_task.title, id="edit-title")
            with Horizontal(classes="editor-row"):
                with Vertical(classes="editor-field"):
                    yield Static("DATE", classes="field-label")
                    yield Input(
                        value=(
                            self.edited_task.due_date.isoformat()
                            if self.edited_task.due_date
                            else ""
                        ),
                        placeholder="YYYY-MM-DD",
                        id="edit-date",
                    )
                with Vertical(classes="editor-field"):
                    yield Static("TIME", classes="field-label")
                    yield Input(
                        value=(
                            self.edited_task.scheduled_time.strftime("%H:%M")
                            if self.edited_task.scheduled_time
                            else ""
                        ),
                        placeholder="HH:MM",
                        id="edit-time",
                    )
                with Vertical(classes="editor-field short-field"):
                    yield Static("MIN", classes="field-label")
                    yield Input(
                        value=str(self.edited_task.duration_minutes),
                        id="edit-duration",
                    )
            with Horizontal(classes="editor-row"):
                with Vertical(classes="editor-field"):
                    yield Static("AREA", classes="field-label")
                    yield Input(value=self.edited_task.area, id="edit-area")
                with Vertical(classes="editor-field"):
                    yield Static("PRIORITY", classes="field-label")
                    yield Input(value=self.edited_task.priority, id="edit-priority")
            yield Static("NOTES", classes="field-label")
            yield TextArea(self.edited_task.description, id="edit-notes")
            yield Static("", id="editor-error")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel-edit")
                yield Button("Save changes", id="save-task", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#edit-title", Input).focus()
        self.query_one("#edit-title", Input).action_end()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-edit":
            self.dismiss(None)
            return
        if event.button.id != "save-task":
            return

        try:
            edit = self._read_edit()
        except ValueError as exc:
            self.query_one("#editor-error", Static).update(str(exc))
            return
        self.dismiss(edit)

    def _read_edit(self) -> TaskEdit:
        title = self.query_one("#edit-title", Input).value.strip()
        if not title:
            raise ValueError("A task needs a title.")

        date_value = self.query_one("#edit-date", Input).value.strip()
        time_value = self.query_one("#edit-time", Input).value.strip()
        duration_value = self.query_one("#edit-duration", Input).value.strip()
        area = self.query_one("#edit-area", Input).value.strip() or "personal"
        priority = self.query_one("#edit-priority", Input).value.strip().lower()
        if priority not in VALID_PRIORITIES:
            raise ValueError("Priority must be low, medium, high, or critical.")

        try:
            due_date = date.fromisoformat(date_value) if date_value else None
        except ValueError as exc:
            raise ValueError("Date must use YYYY-MM-DD.") from exc
        try:
            scheduled_time = time.fromisoformat(time_value) if time_value else None
        except ValueError as exc:
            raise ValueError("Time must use HH:MM in 24-hour time.") from exc
        try:
            duration_minutes = int(duration_value)
        except ValueError as exc:
            raise ValueError("Minutes must be a whole number.") from exc
        if not 1 <= duration_minutes <= 1440:
            raise ValueError("Minutes must be between 1 and 1440.")

        return TaskEdit(
            task_id=self.edited_task.id,
            changes={
                "title": title,
                "due_date": due_date,
                "scheduled_time": scheduled_time,
                "duration_minutes": duration_minutes,
                "area": area,
                "priority": priority,
                "description": self.query_one("#edit-notes", TextArea).text.strip(),
            },
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDeleteScreen(ModalScreen[str | None]):
    """Require an explicit second action before deleting a Markdown task."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, task: Task) -> None:
        super().__init__()
        self.deleted_task = task

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static("DELETE TASK?", classes="modal-kicker danger-copy")
            yield Static(
                f"[b]{escape(self.deleted_task.title)}[/b]\n\n"
                "This removes its Markdown file. This cannot be undone.",
                classes="modal-copy",
            )
            with Horizontal(classes="modal-actions"):
                yield Button("Keep task", id="cancel-delete")
                yield Button("Delete", id="confirm-delete", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-delete":
            self.dismiss(self.deleted_task.id)
        elif event.button.id == "cancel-delete":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
