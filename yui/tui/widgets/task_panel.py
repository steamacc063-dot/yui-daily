"""Right-panel widget — task board."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from yui import Task

_ICONS = {
    "todo": "[#6b6b6b]○[/]",
    "in_progress": "[#c2915e]◑[/]",
    "done": "[#7c9a6e]●[/]",
    "blocked": "[#a05050]×[/]",
}


class TaskPanel(Widget):
    """Minimal task list."""

    def compose(self) -> ComposeResult:
        yield Static("[#484848]  tasks[/]")
        yield VerticalScroll(id="task-list")

    def refresh_tasks(self, tasks: list[Task]) -> None:
        container = self.query_one("#task-list", VerticalScroll)
        container.remove_children()
        if not tasks:
            container.mount(Static("  [#484848]—[/]"))
            return
        for task in tasks:
            icon = _ICONS.get(task.status, "○")
            title_color = "#7c9a6e" if task.status == "done" else "#999999"
            container.mount(Static(
                f"  {icon} [{title_color}]{task.title[:30]}[/]"
            ))

    def refresh_from_board(self, board: dict[str, list[Task]]) -> None:
        container = self.query_one("#task-list", VerticalScroll)
        container.remove_children()
        sections = {"in_progress": "doing", "todo": "todo", "blocked": "blocked", "done": "done"}
        for status, label in sections.items():
            tasks = board.get(status, [])
            if not tasks:
                continue
            container.mount(Static(f"\n  [#484848]{label}[/]  [#484848]{len(tasks)}[/]"))
            for task in tasks[:6]:
                icon = _ICONS.get(task.status, "○")
                title_color = "#7c9a6e" if task.status == "done" else "#999999"
                container.mount(Static(f"   {icon} [{title_color}]{task.title[:28]}[/]"))
