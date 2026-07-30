"""Settings screen — full API and system configuration."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from yui.config import NexusConfig
from yui.core.llm import AGENT_MODELS, SONAR_MODELS, resolve_model
from yui.tui.theme_menu import ThemeMenuScreen

# ── Helpers ──────────────────────────────────────────────────────────────────

def _row(label: str, value_widget) -> list:
    """Return a label + value pair for a settings row."""
    return [Static(f"[#6b6b6b]{label}[/]", classes="settings-label"), value_widget]


def _display(text: str) -> Static:
    return Static(f"[#999999]{text}[/]", classes="settings-value")


# ── Screen ───────────────────────────────────────────────────────────────────


class SettingsScreen(Screen):
    """Full-page settings with sections for API, models, search, context, and system."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = NexusConfig.load()

    def compose(self) -> ComposeResult:
        c = self._config

        with Vertical(id="settings-frame"):
            yield Static("[#8b7ec8]settings[/]", id="settings-title")

            with VerticalScroll():
                # ── API ───────────────────────────────────────────
                yield Static("[#484848]api[/]", classes="settings-section")

                yield Static("[#6b6b6b]  provider[/]  [#484848]perplexity / codex[/]")
                yield Input(
                    value=c.provider,
                    placeholder="perplexity",
                    id="input-provider",
                )
                yield Static("[#6b6b6b]  backup provider[/]  [#484848]none / codex / perplexity[/]")
                yield Input(
                    value=c.backup_provider,
                    placeholder="none",
                    id="input-backup-provider",
                )
                yield Static("[#6b6b6b]  perplexity api key[/]")
                yield Input(
                    value=c.perplexity_api_key,
                    placeholder="pplx-...",
                    password=True,
                    id="input-api-key",
                )
                yield Static("[#6b6b6b]  codex command[/]")
                yield Input(
                    value=c.codex_command,
                    placeholder="codex",
                    id="input-codex-command",
                )
                yield Static("[#6b6b6b]  codex model[/]")
                yield Input(
                    value=c.codex_model,
                    placeholder="gpt-5.4",
                    id="input-codex-model",
                )
                yield Static("[#6b6b6b]  codex timeout seconds[/]")
                yield Input(
                    value=str(c.codex_timeout_seconds),
                    placeholder="60",
                    id="input-codex-timeout",
                )

                # ── Models ────────────────────────────────────────
                yield Static("[#484848]models[/]", classes="settings-section")

                yield Static("[#6b6b6b]  agent model[/]")
                yield Input(
                    value=c.model,
                    placeholder="perplexity/sonar",
                    id="input-model",
                )
                yield Static("[#6b6b6b]  research model[/]")
                yield Input(
                    value=c.research_model,
                    placeholder="sonar-pro",
                    id="input-research-model",
                )

                # Model reference
                agent_list = "  ".join(sorted(AGENT_MODELS.keys()))
                sonar_list = "  ".join(SONAR_MODELS)
                yield Static(
                    f"[#484848]  agent: {agent_list}[/]\n"
                    f"[#484848]  sonar: {sonar_list}[/]"
                )

                # ── Generation ────────────────────────────────────
                yield Static("[#484848]generation[/]", classes="settings-section")

                yield Static("[#6b6b6b]  temperature  [/][#484848]0.0 − 1.0[/]")
                yield Input(
                    value=str(c.temperature),
                    placeholder="0.7",
                    id="input-temperature",
                )
                yield Static("[#6b6b6b]  max output tokens[/]")
                yield Input(
                    value=str(c.max_output_tokens),
                    placeholder="4096",
                    id="input-max-tokens",
                )
                yield Static("[#6b6b6b]  reasoning[/]  [#484848]off  low  medium  high[/]")
                yield Input(
                    value=c.reasoning,
                    placeholder="off",
                    id="input-reasoning",
                )

                # ── Tools ─────────────────────────────────────────
                yield Static("[#484848]tools[/]", classes="settings-section")

                yield Static("[#6b6b6b]  web search[/]  [#484848]on / off[/]")
                yield Input(
                    value="on" if c.web_search else "off",
                    placeholder="on",
                    id="input-web-search",
                )
                yield Static("[#6b6b6b]  fetch url[/]  [#484848]on / off[/]")
                yield Input(
                    value="on" if c.fetch_url else "off",
                    placeholder="on",
                    id="input-fetch-url",
                )
                yield Static(
                    "[#6b6b6b]  search recency filter[/]  [#484848]day  week  month  year  none[/]"
                )
                yield Input(
                    value=c.search_recency_filter,
                    placeholder="none",
                    id="input-recency",
                )

                # ── Context ───────────────────────────────────────
                yield Static("[#484848]context[/]", classes="settings-section")

                yield Static("[#6b6b6b]  max context tokens[/]")
                yield Input(
                    value=str(c.max_context_tokens),
                    placeholder="8000",
                    id="input-context-tokens",
                )
                yield Static(
                    "[#6b6b6b]  memory decay hours[/]  "
                    "[#484848]stale memories below 0.3 importance[/]"
                )
                yield Input(
                    value=str(c.memory_decay_hours),
                    placeholder="72",
                    id="input-decay-hours",
                )
                yield Static("[#6b6b6b]  auto-research[/]  [#484848]on / off[/]")
                yield Input(
                    value="on" if c.auto_research else "off",
                    placeholder="on",
                    id="input-auto-research",
                )

                # ── System ────────────────────────────────────────
                yield Static("[#484848]system[/]", classes="settings-section")

                yield Static(f"[#6b6b6b]  vault[/]  [#484848]{c.obsidian_vault_path or '—'}[/]")
                yield Static(
                    "[#6b6b6b]  theme[/]  [#484848]ghostty-style name (catppuccin-mocha)[/]"
                )
                yield Input(
                    value=c.theme,
                    placeholder="textual-dark",
                    id="input-theme",
                )
                yield Button("theme menu", id="btn-theme-menu")
                available = "  ".join(sorted(self.app.available_themes.keys())[:8])
                yield Static(f"[#484848]  available: {available}[/]")

                # ── Actions ───────────────────────────────────────
                yield Static("")
                yield Button("save", id="btn-save", classes="btn-accent")
                yield Button("cancel", id="btn-cancel")
                yield Button("reset app (rerun onboarding)", id="btn-reset")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.app.pop_screen()
            return

        if event.button.id == "btn-save":
            self._save()
            self.app.pop_screen()
            return

        if event.button.id == "btn-reset":
            self.app.pop_screen()
            from yui.tui.app import NexusApp
            if isinstance(self.app, NexusApp):
                self.app.reset_to_onboarding()
            return

        if event.button.id == "btn-theme-menu":
            self._open_theme_menu()

    def _save(self) -> None:
        """Read all inputs and persist to config."""
        c = self._config

        # Providers
        c.provider = (self._val("input-provider") or c.provider).lower()
        if c.provider not in ("perplexity", "codex"):
            c.provider = "perplexity"
        c.backup_provider = (
            self._val("input-backup-provider") or c.backup_provider
        ).lower()
        if c.backup_provider not in ("none", "perplexity", "codex"):
            c.backup_provider = "none"
        if c.backup_provider == c.provider:
            c.backup_provider = "none"
        api_key = self._val("input-api-key")
        needs_perplexity = c.provider == "perplexity" or c.backup_provider == "perplexity"
        if api_key or not needs_perplexity:
            c.perplexity_api_key = api_key
        c.codex_command = self._val("input-codex-command") or "codex"
        c.codex_model = self._val("input-codex-model") or c.codex_model
        try:
            c.codex_timeout_seconds = int(
                self._val("input-codex-timeout") or str(c.codex_timeout_seconds)
            )
            c.codex_timeout_seconds = max(30, c.codex_timeout_seconds)
        except ValueError:
            pass

        # Models
        c.model = resolve_model(self._val("input-model") or c.model)
        c.research_model = self._val("input-research-model") or c.research_model

        # Generation
        try:
            c.temperature = float(self._val("input-temperature") or "0.7")
            c.temperature = max(0.0, min(1.0, c.temperature))
        except ValueError:
            pass
        try:
            c.max_output_tokens = int(self._val("input-max-tokens") or "4096")
        except ValueError:
            pass
        c.reasoning = self._val("input-reasoning") or "off"
        if c.reasoning not in ("off", "low", "medium", "high"):
            c.reasoning = "off"

        # Tools
        c.web_search = self._val("input-web-search").lower() in ("on", "true", "1", "yes")
        c.fetch_url = self._val("input-fetch-url").lower() in ("on", "true", "1", "yes")
        c.search_recency_filter = self._val("input-recency") or "none"
        if c.search_recency_filter not in ("day", "week", "month", "year", "none"):
            c.search_recency_filter = "none"

        # Context
        try:
            c.max_context_tokens = int(self._val("input-context-tokens") or "8000")
        except ValueError:
            pass
        try:
            c.memory_decay_hours = int(self._val("input-decay-hours") or "72")
        except ValueError:
            pass
        c.auto_research = self._val("input-auto-research").lower() in ("on", "true", "1", "yes")
        c.theme = self._val("input-theme") or c.theme

        # Apply to running app + LLM client
        from yui.tui.app import NexusApp
        if isinstance(self.app, NexusApp):
            self.app.rebuild_llm_client(c)
            if self.app.context_engine:
                self.app.context_engine.max_tokens = c.max_context_tokens
            c.theme = self.app.apply_theme(c.theme)
            if self.app.config:
                c.imported_themes = list(self.app.config.imported_themes)
            self.app.config = c

        c.save()

    def _open_theme_menu(self) -> None:
        current = self._val("input-theme") or self._config.theme
        self.app.push_screen(ThemeMenuScreen(current), self._on_theme_menu_closed)

    def _on_theme_menu_closed(self, selected_theme: str | None) -> None:
        if not selected_theme:
            return
        from yui.tui.app import NexusApp
        if isinstance(self.app, NexusApp):
            selected_theme = self.app.apply_theme(selected_theme)
        try:
            theme_input = self.query_one("#input-theme", Input)
            theme_input.value = selected_theme
        except Exception:
            return

    def _val(self, input_id: str) -> str:
        try:
            return self.query_one(f"#{input_id}", Input).value.strip()
        except Exception:
            return ""

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key:
            return "—"
        if len(key) <= 8:
            return "••••"
        return key[:4] + "•" * (len(key) - 8) + key[-4:]
