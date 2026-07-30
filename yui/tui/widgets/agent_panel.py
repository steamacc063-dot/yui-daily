"""Right-panel widget — agent status list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

_DOTS = {
    "idle": "[#484848]·[/]",
    "thinking": "[#8b7ec8]·[/]",
    "working": "[#c2915e]·[/]",
    "discussing": "[#7c9a6e]·[/]",
    "offline": "[#484848]·[/]",
}

_STATUS = {
    "idle": "[#484848]idle[/]",
    "thinking": "[italic #8b7ec8]thinking[/]",
    "working": "[#c2915e]working[/]",
    "discussing": "[#7c9a6e]discussing[/]",
    "offline": "[#484848]offline[/]",
}


class AgentPanel(Widget):
    """Displays agent statuses."""

    def compose(self) -> ComposeResult:
        yield Static("[#484848]  agents[/]")
        yield VerticalScroll(id="agent-cards")

    def refresh_agents(self, agents: list[dict]) -> None:
        container = self.query_one("#agent-cards", VerticalScroll)
        container.remove_children()
        for agent in agents:
            status = agent.get("status", "idle")
            dot = _DOTS.get(status, _DOTS["idle"])
            st = _STATUS.get(status, _STATUS["idle"])
            color = agent.get("color", "#8b7ec8")
            card = Static(
                f"  {dot} [{color}]{agent['name']}[/]  {st}\n"
                f"    [#484848]{agent['role']}[/]",
            )
            container.mount(card)
