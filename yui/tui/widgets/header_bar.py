"""Branded header for the Yui daily planner."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class HeaderBar(Widget):
    """A quiet, editorial top bar with live local-storage status."""

    date_text: reactive[str] = reactive("")
    status_text: reactive[str] = reactive("LOCAL · READY")

    def compose(self) -> ComposeResult:
        yield Static("結", id="mark")
        yield Static("[b]YUI[/b]\nDAILY SYSTEM", id="brand")
        yield Static("", id="header-date")
        yield Static("", id="header-status")

    def watch_date_text(self, value: str) -> None:
        self.query_one("#header-date", Static).update(value.upper())

    def watch_status_text(self, value: str) -> None:
        self.query_one("#header-status", Static).update(f"●  {value}")
