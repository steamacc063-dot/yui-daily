"""Yui — a local-first daily agenda and task system."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Resize
from textual.widgets import Footer

from yui.config import CONFIG_DIR, NexusConfig
from yui.obsidian.tasks import TaskTracker
from yui.obsidian.vault import ObsidianVault
from yui.productivity import parse_quick_task
from yui.tui.widgets.agenda_view import (
    AgendaView,
    QuickTaskSubmitted,
    TaskSelected,
)
from yui.tui.widgets.focus_panel import FocusPanel
from yui.tui.widgets.header_bar import HeaderBar
from yui.tui.widgets.sidebar import Sidebar, ViewSelected
from yui.tui.widgets.task_editor import ConfirmDeleteScreen, TaskEdit, TaskEditorScreen


class YuiApp(App):
    """Keyboard-first terminal planner backed by human-readable Markdown."""

    CSS_PATH = "theme.tcss"
    TITLE = "Yui Daily"
    SUB_TITLE = "Local-first agenda"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("n", "new_task", "New task", priority=False),
        Binding("space", "toggle_complete", "Complete", priority=False),
        Binding("p", "cycle_priority", "Priority", show=False, priority=False),
        Binding("m", "move_tomorrow", "Tomorrow", show=False, priority=False),
        Binding("e", "edit_task", "Edit", priority=False),
        Binding("x", "delete_task", "Delete", show=False, priority=False),
        Binding("t", "show_today", "Today", show=False, priority=False),
        Binding("i", "show_inbox", "Inbox", show=False, priority=False),
        Binding("u", "show_upcoming", "Upcoming", show=False, priority=False),
        Binding("c", "show_completed", "Completed", show=False, priority=False),
        Binding("left_square_bracket", "previous_day", "Previous day", show=False),
        Binding("right_square_bracket", "next_day", "Next day", show=False),
        Binding("f1", "show_help", "Help"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        vault_path: str | Path | None = None,
        today_factory: Callable[[], date] | None = None,
    ) -> None:
        super().__init__()
        self._vault_override = Path(vault_path) if vault_path else None
        self._today_factory = today_factory or date.today
        self.vault: ObsidianVault | None = None
        self.task_tracker: TaskTracker | None = None
        self.current_view = "today"
        self.selected_day = self._today_factory()
        self.current_task_id: str | None = None

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Horizontal(id="workspace"):
            yield Sidebar()
            yield AgendaView()
            yield FocusPanel(id="focus-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._initialize_storage()
        self.query_one(HeaderBar).date_text = self._today_factory().strftime(
            "%A · %d %B %Y"
        )
        self.refresh_workspace()
        self.query_one(AgendaView).focus_tasks()

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < 96, "compact")

    def _initialize_storage(self) -> None:
        config = NexusConfig.load()
        if self._vault_override:
            path = self._vault_override
        elif config.obsidian_vault_path:
            path = config.vault
        else:
            path = CONFIG_DIR / "vault"
            config.obsidian_vault_path = str(path)
            config.save()

        self.vault = ObsidianVault(path)
        self.vault.ensure_structure()
        self.vault.write_welcome()
        self.task_tracker = TaskTracker(self.vault)
        self.query_one(HeaderBar).status_text = f"LOCAL · {path.name.upper()}"

    def refresh_workspace(self, *, preferred_id: str | None = None) -> None:
        if not self.task_tracker:
            return

        today = self._today_factory()
        tasks = []
        title = ""
        subtitle = ""
        reference_day: date | None = None
        show_dates = False

        if self.current_view in {"today", "tomorrow", "day"}:
            if self.current_view == "today":
                self.selected_day = today
            elif self.current_view == "tomorrow":
                self.selected_day = today + timedelta(days=1)
            reference_day = self.selected_day
            tasks = self.task_tracker.agenda(
                self.selected_day,
                include_overdue=self.selected_day == today,
            )
            title = self.selected_day.strftime("%A, %B %d").replace(" 0", " ")
            incomplete = sum(task.status != "done" for task in tasks)
            subtitle = f"{incomplete} open · make room for one good day"
        elif self.current_view == "upcoming":
            tasks = self.task_tracker.upcoming(today)
            title = "Upcoming"
            subtitle = "The next 14 days, without the noise"
            show_dates = True
        elif self.current_view == "inbox":
            tasks = self.task_tracker.inbox()
            title = "Inbox"
            subtitle = "Unsorted thoughts waiting for a home"
        elif self.current_view == "completed":
            tasks = self.task_tracker.completed()
            title = "Completed"
            subtitle = "A quiet record of forward motion"
            show_dates = True

        agenda = self.query_one(AgendaView)
        agenda.refresh_view(
            tasks,
            title=title,
            subtitle=subtitle,
            reference_day=reference_day,
            show_dates=show_dates,
            preferred_id=preferred_id or self.current_task_id,
        )
        selected_task = agenda.agenda_list.selected_task
        self.current_task_id = selected_task.id if selected_task else None

        summary = self.task_tracker.summarize(tasks)
        focus = self.query_one(FocusPanel)
        focus.update_summary(summary)
        focus.update_task(
            self.task_tracker.get(self.current_task_id) if self.current_task_id else None
        )
        self._refresh_sidebar(today)

    def _refresh_sidebar(self, today: date) -> None:
        if not self.task_tracker:
            return
        all_tasks = self.task_tracker.list_all()
        counts = {
            "today": len(self.task_tracker.agenda(today, include_overdue=True)),
            "tomorrow": len(self.task_tracker.agenda(today + timedelta(days=1))),
            "upcoming": len(self.task_tracker.upcoming(today)),
            "inbox": len(self.task_tracker.inbox()),
            "completed": len([task for task in all_tasks if task.status == "done"]),
        }
        sidebar = self.query_one(Sidebar)
        sidebar.update_counts(counts)
        sidebar.set_active(self.current_view if self.current_view != "day" else "")

    def on_view_selected(self, event: ViewSelected) -> None:
        self._switch_view(event.view)

    def on_task_selected(self, event: TaskSelected) -> None:
        self.current_task_id = event.task_id
        if self.task_tracker:
            self.query_one(FocusPanel).update_task(
                self.task_tracker.get(event.task_id) if event.task_id else None
            )

    def on_quick_task_submitted(self, event: QuickTaskSubmitted) -> None:
        if not self.task_tracker:
            return
        try:
            default_day = (
                self.selected_day
                if self.current_view in {"today", "tomorrow", "day"}
                else self._today_factory()
            )
            draft = parse_quick_task(event.text, default_date=default_day)
            due_date = (
                None
                if self.current_view == "inbox" and not draft.date_was_explicit
                else draft.due_date
            )
            task = self.task_tracker.create(
                draft.title,
                due_date=due_date,
                scheduled_time=draft.scheduled_time,
                duration_minutes=draft.duration_minutes,
                area=draft.area,
                priority=draft.priority,
            )
        except ValueError as exc:
            self.notify(str(exc), title="Could not add task", severity="error")
            self.query_one(AgendaView).focus_capture()
            return

        self.current_task_id = task.id
        self.refresh_workspace(preferred_id=task.id)
        self.query_one(AgendaView).focus_tasks()
        self.notify("Task captured", title="Saved locally", timeout=1.5)

    def _switch_view(self, view: str) -> None:
        self.current_view = view
        self.current_task_id = None
        self.refresh_workspace()
        self.query_one(AgendaView).focus_tasks()

    def action_new_task(self) -> None:
        self.query_one(AgendaView).focus_capture()

    def action_toggle_complete(self) -> None:
        if not self.task_tracker or not self.current_task_id:
            return
        task = self.task_tracker.get(self.current_task_id)
        if not task:
            return
        self.task_tracker.set_completed(task.id, completed=task.status != "done")
        self.refresh_workspace(preferred_id=task.id)
        self.query_one(AgendaView).focus_tasks()

    def action_cycle_priority(self) -> None:
        if not self.task_tracker or not self.current_task_id:
            return
        task = self.task_tracker.get(self.current_task_id)
        if not task:
            return
        priorities = ("low", "medium", "high", "critical")
        next_priority = priorities[(priorities.index(task.priority) + 1) % len(priorities)]
        self.task_tracker.update(task.id, priority=next_priority)
        self.refresh_workspace(preferred_id=task.id)

    def action_move_tomorrow(self) -> None:
        if not self.task_tracker or not self.current_task_id:
            return
        task = self.task_tracker.get(self.current_task_id)
        if not task:
            return
        self.task_tracker.update(
            task.id,
            due_date=self._today_factory() + timedelta(days=1),
            status="todo",
            completed_at=None,
        )
        self.refresh_workspace()
        self.notify("Moved to tomorrow", timeout=1.5)

    def action_edit_task(self) -> None:
        if not self.task_tracker or not self.current_task_id:
            return
        task = self.task_tracker.get(self.current_task_id)
        if task:
            self.push_screen(TaskEditorScreen(task), self._apply_task_edit)

    def _apply_task_edit(self, edit: TaskEdit | None) -> None:
        if not edit or not self.task_tracker:
            return
        self.task_tracker.update(edit.task_id, **edit.changes)
        self.current_task_id = edit.task_id
        self.refresh_workspace(preferred_id=edit.task_id)
        self.query_one(AgendaView).focus_tasks()
        self.notify("Changes saved", timeout=1.5)

    def action_delete_task(self) -> None:
        if not self.task_tracker or not self.current_task_id:
            return
        task = self.task_tracker.get(self.current_task_id)
        if task:
            self.push_screen(ConfirmDeleteScreen(task), self._delete_confirmed)

    def _delete_confirmed(self, task_id: str | None) -> None:
        if not task_id or not self.task_tracker:
            return
        if self.task_tracker.delete(task_id):
            self.current_task_id = None
            self.refresh_workspace()
            self.query_one(AgendaView).focus_tasks()
            self.notify("Task deleted", timeout=1.5)

    def action_show_today(self) -> None:
        self._switch_view("today")

    def action_show_inbox(self) -> None:
        self._switch_view("inbox")

    def action_show_upcoming(self) -> None:
        self._switch_view("upcoming")

    def action_show_completed(self) -> None:
        self._switch_view("completed")

    def action_previous_day(self) -> None:
        self.current_view = "day"
        self.selected_day -= timedelta(days=1)
        self.refresh_workspace()

    def action_next_day(self) -> None:
        self.current_view = "day"
        self.selected_day += timedelta(days=1)
        self.refresh_workspace()

    def action_show_help(self) -> None:
        self.notify(
            "N capture · ↑↓ select · Space complete · P priority · M tomorrow · [ ] day",
            title="Keyboard map",
            timeout=5,
        )


# Preserve the former import name for downstream launch scripts.
NexusApp = YuiApp
