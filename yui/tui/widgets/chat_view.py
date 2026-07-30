"""Central chat panel — message log + input."""

from __future__ import annotations

from datetime import datetime

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message as TMessage
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static


class UserSubmitted(TMessage):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class ChatView(Widget):
    """Chat area — scrolling log and input."""

    DEFAULT_CSS = """
    ChatView { width: 1fr; layout: vertical; }
    """

    channel: reactive[str] = reactive("general")

    def compose(self) -> ComposeResult:
        yield Static("", id="channel-header")
        yield RichLog(highlight=True, markup=True, wrap=True, id="chat-log")
        with Vertical(id="input-area"):
            yield Input(placeholder="message  ·  / for commands", id="message-input")

    def watch_channel(self, value: str) -> None:
        header = self.query_one("#channel-header", Static)
        header.update(f"  [#484848]# {value}[/]")

    def add_message(
        self,
        sender: str,
        content: str,
        color: str = "#8b7ec8",
        timestamp: datetime | None = None,
    ) -> None:
        log = self.query_one("#chat-log", RichLog)
        ts = (timestamp or datetime.now()).strftime("%H:%M")
        log.write(f"[#484848]{ts}[/]  [bold {color}]{escape(sender)}[/]")
        log.write(f"  {escape(content)}\n")

    def add_system_message(self, content: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        ts = datetime.now().strftime("%H:%M")
        log.write(f"[#484848]{ts}[/]  [#6b6b6b]{escape(content)}[/]\n")

    def add_thinking_indicator(self, agent_name: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(f"  [italic #8b7ec8]{escape(agent_name)} …[/]")

    def clear_log(self) -> None:
        self.query_one("#chat-log", RichLog).clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.post_message(UserSubmitted(text))

    def focus_input(self) -> None:
        self.query_one("#message-input", Input).focus()

    def stream_token(self, token: str) -> None:
        self.query_one("#chat-log", RichLog).write(
            escape(token),
            shrink=False,
            scroll_end=True,
        )
