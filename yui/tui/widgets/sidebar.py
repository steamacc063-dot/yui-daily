"""Navigation for the local-first daily planner."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static


class ViewSelected(Message):
    """Posted when the user selects a productivity view."""

    def __init__(self, view: str) -> None:
        super().__init__()
        self.view = view


class Sidebar(Widget):
    """Compact agenda navigation with live task counts."""

    VIEWS = (
        ("today", "TODAY", "T"),
        ("tomorrow", "TOMORROW", ">"),
        ("upcoming", "UPCOMING", "U"),
        ("inbox", "INBOX", "I"),
        ("completed", "COMPLETED", "C"),
    )

    def compose(self) -> ComposeResult:
        yield Static("PLAN", classes="rail-label")
        yield ListView(
            *(
                ListItem(
                    Label(f"{glyph}  {label}", id=f"label-{view}"),
                    id=f"view-{view}",
                )
                for view, label, glyph in self.VIEWS
            ),
            id="view-list",
        )
        yield Static("AREAS", classes="rail-label")
        yield Static("  · PERSONAL\n  · WORK\n  · STUDIO", id="area-list")
        yield Static(
            "[b]CAPTURE FAST[/b]\n"
            "@09:30  /30m\n"
            "#work    !high\n"
            "tomorrow",
            id="capture-legend",
        )

    def on_mount(self) -> None:
        self.set_active("today")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id.startswith("view-"):
            view = item_id.removeprefix("view-")
            self.set_active(view)
            self.post_message(ViewSelected(view))

    def set_active(self, view: str) -> None:
        for view_name, _, _ in self.VIEWS:
            try:
                item = self.query_one(f"#view-{view_name}", ListItem)
                item.set_class(view_name == view, "active")
            except Exception:
                continue

    def update_counts(self, counts: dict[str, int]) -> None:
        for view, label, glyph in self.VIEWS:
            try:
                count = counts.get(view, 0)
                suffix = f"  {count:02d}" if count else ""
                self.query_one(f"#label-{view}", Label).update(
                    f"{glyph}  {label}{suffix}"
                )
            except Exception:
                continue


# Compatibility for imports from the former agent-oriented UI.
ChannelSelected = ViewSelected
