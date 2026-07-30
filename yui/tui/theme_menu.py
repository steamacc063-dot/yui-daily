"""Theme picker and Ghostty .txt importer modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static

from yui.tui.theme_utils import resolve_theme_name


class ThemeMenuScreen(ModalScreen[str | None]):
    """Pick an installed theme or import a Ghostty .txt theme file."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "apply_selection", "Apply"),
    ]

    CSS = """
    ThemeMenuScreen {
        align: center middle;
        background: $background 80%;
    }

    #theme-menu-frame {
        width: 72;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: round $border-blurred;
        padding: 1 2;
    }

    #theme-menu-title {
        text-align: center;
        color: $primary;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #theme-options {
        height: 14;
        border: round $border-blurred;
        margin: 0 0 1 0;
    }

    #theme-status {
        color: $foreground-muted;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, current_theme: str) -> None:
        super().__init__()
        self._current_theme = current_theme

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-menu-frame"):
            yield Static("[#8b7ec8]themes[/]", id="theme-menu-title")
            yield OptionList(id="theme-options")
            yield Static(
                "[#6b6b6b]pick a theme or import a Ghostty .txt file[/]",
                id="theme-status",
            )
            yield Input(placeholder="~/Downloads/theme.txt", id="input-theme-file")
            yield Button("import .txt", id="btn-import-theme")
            yield Button("apply selection", id="btn-apply-theme", classes="btn-accent")
            yield Button("cancel", id="btn-cancel-theme")

    def on_mount(self) -> None:
        self._refresh_options()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel-theme":
            self.dismiss(None)
            return
        if event.button.id == "btn-apply-theme":
            self.dismiss(self._selected_theme())
            return
        if event.button.id == "btn-import-theme":
            self._import_theme_file()

    def on_option_list_option_selected(self, _: OptionList.OptionSelected) -> None:
        self.dismiss(self._selected_theme())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_apply_selection(self) -> None:
        self.dismiss(self._selected_theme())

    def _import_theme_file(self) -> None:
        file_path = self.query_one("#input-theme-file", Input).value.strip()
        status = self.query_one("#theme-status", Static)
        if not file_path:
            status.update("[#a05050]enter a .txt file path first[/]")
            return

        from yui.tui.app import NexusApp
        if not isinstance(self.app, NexusApp):
            status.update("[#a05050]theme import unavailable[/]")
            return

        try:
            imported_name = self.app.import_ghostty_theme(file_path)
        except Exception as exc:
            status.update(f"[#a05050]{exc}[/]")
            return

        self._current_theme = imported_name
        self.query_one("#input-theme-file", Input).value = ""
        status.update(f"[#7c9a6e]imported: {imported_name}[/]")
        self._refresh_options()

    def _refresh_options(self) -> None:
        options = self.query_one("#theme-options", OptionList)
        options.clear_options()

        names = sorted(self.app.available_themes.keys())
        options.add_options(names)

        selected = resolve_theme_name(self._current_theme, names)
        if selected in names:
            options.highlighted = names.index(selected)

    def _selected_theme(self) -> str:
        options = self.query_one("#theme-options", OptionList)
        index = options.highlighted
        if index is None:
            return resolve_theme_name(self._current_theme, self.app.available_themes.keys())
        option = options.get_option_at_index(index)
        return str(option.prompt)
