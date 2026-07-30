"""Central agenda surface and quick-capture input."""

from __future__ import annotations

from datetime import date, time

from rich.markup import escape
from textual.app import ComposeResult
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from yui import Task


class QuickTaskSubmitted(Message):
    """A quick-capture string is ready for parsing."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class TaskSelected(Message):
    """The selected task changed."""

    def __init__(self, task_id: str | None) -> None:
        super().__init__()
        self.task_id = task_id


class AgendaList(Static):
    """Keyboard-first task list rendered as a compact daily timeline."""

    can_focus = True

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("", id=id, markup=True)
        self.tasks: list[Task] = []
        self.selected_index = 0
        self.reference_day: date | None = None
        self.show_dates = False

    @property
    def selected_task(self) -> Task | None:
        if not self.tasks:
            return None
        return self.tasks[self.selected_index]

    def set_tasks(
        self,
        tasks: list[Task],
        *,
        reference_day: date | None,
        show_dates: bool = False,
        preferred_id: str | None = None,
    ) -> None:
        self.tasks = list(tasks)
        self.reference_day = reference_day
        self.show_dates = show_dates
        ids = [task.id for task in self.tasks]
        self.selected_index = ids.index(preferred_id) if preferred_id in ids else 0
        self._refresh_markup()
        self._post_selection()

    def select_delta(self, delta: int) -> None:
        if not self.tasks:
            return
        self.selected_index = (self.selected_index + delta) % len(self.tasks)
        self._refresh_markup()
        self._post_selection()

    def select_task(self, task_id: str) -> None:
        ids = [task.id for task in self.tasks]
        if task_id in ids:
            self.selected_index = ids.index(task_id)
            self._refresh_markup()
            self._post_selection()

    def on_key(self, event: Key) -> None:
        if event.key in {"up", "k"}:
            self.select_delta(-1)
            event.stop()
        elif event.key in {"down", "j"}:
            self.select_delta(1)
            event.stop()

    def _post_selection(self) -> None:
        selected = self.selected_task
        self.post_message(TaskSelected(selected.id if selected else None))

    def _refresh_markup(self) -> None:
        if not self.tasks:
            self.update(
                "\n\n        [#76786f]NOTHING HERE YET[/]\n"
                "        [#a7a89f]Press [b]N[/b] and capture what matters.[/]"
            )
            return

        lines: list[str] = []
        previous_section = ""
        for index, task in enumerate(self.tasks):
            section = self._section_for(task)
            if section != previous_section:
                if lines:
                    lines.append("")
                lines.append(f"[#707268 b]{escape(section)}[/]")
                previous_section = section
            lines.append(self._task_line(task, selected=index == self.selected_index))
        self.update("\n".join(lines))

    def _section_for(self, task: Task) -> str:
        if self.show_dates and task.due_date:
            return task.due_date.strftime("%A · %B %d").upper()
        if self.reference_day and task.due_date and task.due_date < self.reference_day:
            return "OVERDUE"
        if task.status == "done":
            return "COMPLETED"
        if task.scheduled_time is None:
            return "ANYTIME"
        if task.scheduled_time < time(12):
            return "MORNING"
        if task.scheduled_time < time(17):
            return "AFTERNOON"
        return "EVENING"

    def _task_line(self, task: Task, *, selected: bool) -> str:
        when = task.scheduled_time.strftime("%H:%M") if task.scheduled_time else "  ·  "
        marker = "●" if task.status == "done" else "○"
        marker_color = "#8fa879" if task.status == "done" else "#d6a85f"
        title_color = "#77796f" if task.status == "done" else "#e5e2d7"
        priority = {
            "critical": "[#d87562]!![/]",
            "high": "[#d6a85f]![/] ",
            "medium": "   ",
            "low": "[#74766d]·[/] ",
        }.get(task.priority, "   ")
        area = escape(task.area.upper()[:10])
        title = escape(task.title)
        row = (
            f" {when}  [{marker_color}]{marker}[/]  [{title_color}]{title}[/]"
            f"  [#6d7067]{task.duration_minutes}m · {area}[/] {priority}"
        )
        if selected:
            return f"[on #30342b]{row}[/]"
        return row


class AgendaView(Widget):
    """Main view: title, capture, legend, and scrollable timeline."""

    def compose(self) -> ComposeResult:
        yield Static("DAILY AGENDA", id="view-kicker")
        yield Static("", id="view-title")
        yield Static("", id="view-subtitle")
        yield Input(
            placeholder="Add a task…  @14:30  /30m  #work  !high",
            id="quick-add",
        )
        yield Static(
            "ENTER TO SAVE   ·   ↑↓ TO MOVE   ·   SPACE TO COMPLETE",
            id="capture-hint",
        )
        yield AgendaList(id="agenda-list")

    @property
    def agenda_list(self) -> AgendaList:
        return self.query_one("#agenda-list", AgendaList)

    def refresh_view(
        self,
        tasks: list[Task],
        *,
        title: str,
        subtitle: str,
        reference_day: date | None,
        show_dates: bool = False,
        preferred_id: str | None = None,
    ) -> None:
        self.query_one("#view-title", Static).update(title)
        self.query_one("#view-subtitle", Static).update(subtitle)
        self.agenda_list.set_tasks(
            tasks,
            reference_day=reference_day,
            show_dates=show_dates,
            preferred_id=preferred_id,
        )

    def focus_capture(self) -> None:
        self.query_one("#quick-add", Input).focus()

    def focus_tasks(self) -> None:
        self.agenda_list.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "quick-add":
            return
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.post_message(QuickTaskSubmitted(text))
