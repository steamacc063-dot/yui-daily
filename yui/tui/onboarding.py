"""Multi-step onboarding wizard — shown on first launch."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from yui.config import NexusConfig
from yui.core.llm import create_llm_client

LOGO = """[bold #8b7ec8]
        結   y  u  i
[/]"""

STEP_LABELS = ["Welcome", "Provider", "Vault", "Setup", "Ready"]


class OnboardingScreen(Screen):
    """Five-step first-run setup wizard."""

    BINDINGS = [Binding("escape", "app.quit", "Quit")]

    CSS = """
    OnboardingScreen { align: center middle; background: #0d0d0d 90%; }

    #onboard-frame {
        width: 56; height: auto; max-height: 90%;
        border: round #222222; background: #111111; padding: 1 3;
    }
    #onboard-logo { text-align: center; }
    #onboard-dots { text-align: center; height: 1; margin: 0 0 1 0; }
    #onboard-body { height: auto; padding: 0 1; }

    .ob-btn {
        width: 100%; margin: 1 0 0 0;
        background: #1a1a1a; color: #999999;
        border: tall #222222;
    }
    .ob-btn:hover { background: #222222; color: #cccccc; }
    .ob-btn-back {
        background: #141414; color: #6b6b6b;
        width: 100%; margin: 1 0 0 0; border: tall #222222;
    }
    .ob-btn-back:hover { background: #1a1a1a; color: #999999; }

    #onboard-body Input {
        margin: 0 0 1 0; background: #1a1a1a;
        color: #cccccc; border: tall #222222;
    }
    #onboard-body Input:focus { border: tall #8b7ec8; }
    .step-label { color: #484848; text-align: center; margin: 1 0 0 0; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._step = 0
        self._provider = "perplexity"
        self._backup_provider = "none"
        self._api_key = ""
        self._codex_command = "codex"
        self._codex_model = "gpt-5.4"
        self._codex_timeout_seconds = 60
        self._vault_path = ""
        self._agent_feel = ""
        self._agent_strengths = ""
        self._agent_count = 3
        self._agent_roles: list[str] = []
        self._agent_import_paths: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="onboard-frame"):
            yield Static(LOGO, id="onboard-logo")
            yield Static("", id="onboard-dots")
            yield Vertical(id="onboard-body")
            yield Static("", id="onboard-step-label", classes="step-label")

    def on_mount(self) -> None:
        self._show_step()

    # ── Step rendering ────────────────────────────────────────────────────

    def _show_step(self) -> None:
        """Clear body and mount widgets for the current step."""
        body = self.query_one("#onboard-body", Vertical)
        body.remove_children()
        self._update_indicators()

        widgets = [
            self._welcome_widgets,
            self._api_key_widgets,
            self._vault_widgets,
            self._connect_widgets,
            self._ready_widgets,
        ][self._step]()

        body.mount_all(widgets)

        # Step 3 (connect) triggers async work after mount
        if self._step == 3:
            self._do_connect()

    def _update_indicators(self) -> None:
        dots: list[str] = []
        for i in range(5):
            if i < self._step:
                dots.append("[#7c9a6e]●[/]")
            elif i == self._step:
                dots.append("[bold #8b7ec8]●[/]")
            else:
                dots.append("[#484848]○[/]")
        self.query_one("#onboard-dots", Static).update(
            "  " + "  ──  ".join(dots)
        )
        self.query_one("#onboard-step-label", Static).update(
            f"[#484848]{self._step + 1}/5 · {STEP_LABELS[self._step]}[/]"
        )

    # ── Step 0 — Welcome ──────────────────────────────────────────────────

    def _welcome_widgets(self) -> list:
        return [
            Static(
                "[#cccccc]Your terminal. Your agents. Your knowledge.[/]\n"
            ),
            Static(
                "[#6b6b6b]"
                "a multi-agent system that lives in your\n"
                "terminal and stores everything in obsidian.\n\n"
                "  [#8b7ec8]·[/]  Agents with distinct identities\n"
                "  [#8b7ec8]·[/]  Conversations persist to your vault\n"
                "  [#8b7ec8]·[/]  Context is searched, not memorized\n"
                "  [#8b7ec8]·[/]  Tasks tracked like a project board"
                "[/]"
            ),
            Static(""),
            Button("continue", classes="ob-btn"),
        ]

    # ── Step 1 — Provider ─────────────────────────────────────────────────

    def _api_key_widgets(self) -> list:
        existing = NexusConfig.load()
        provider = existing.provider or "perplexity"
        return [
            Static("[#cccccc]choose your backend[/]\n"),
            Static(
                "[#6b6b6b]Perplexity uses the API directly.\n"
                "Codex uses your installed Codex CLI and does not require a Perplexity key.[/]\n"
            ),
            Static("[#484848]provider  [#6b6b6b]perplexity / codex[/]"),
            Input(
                placeholder="perplexity",
                id="input-provider",
                value=provider,
            ),
            Static("[#484848]backup provider  [#6b6b6b]none / codex / perplexity[/]"),
            Input(
                placeholder="none",
                id="input-backup-provider",
                value=existing.backup_provider,
            ),
            Static("[#484848]api key[/]"),
            Input(
                placeholder="pplx-...",
                id="input-api-key",
                password=True,
                value=existing.perplexity_api_key,
            ),
            Static("[#484848]codex command[/]"),
            Input(
                placeholder="codex",
                id="input-codex-command",
                value=existing.codex_command,
            ),
            Static("[#484848]codex model[/]"),
            Input(
                placeholder="gpt-5.4",
                id="input-codex-model",
                value=existing.codex_model,
            ),
            Static("[#484848]codex timeout seconds[/]"),
            Input(
                placeholder="60",
                id="input-codex-timeout",
                value=str(existing.codex_timeout_seconds),
            ),
            Button("continue", classes="ob-btn"),
        ]

    # ── Step 2 — Vault Path ───────────────────────────────────────────────

    def _vault_widgets(self) -> list:
        existing = NexusConfig.load()
        default = existing.obsidian_vault_path or str(Path.home() / "yui-vault")
        return [
            Static("[#cccccc]set your vault[/]\n"),
            Static(
                "[#6b6b6b]Point to an Obsidian vault or any folder.\n"
                "Created if it doesn't exist.[/]\n"
            ),
            Static("[#484848]vault path[/]"),
            Input(placeholder="~/yui-vault", id="input-vault-path", value=default),
            Static(
                "\n[#cccccc]custom agents[/]\n"
                "[#6b6b6b]Describe how workers should feel and what they excel at.\n"
                "Yui will generate AGENT.md workers using the selected backend.[/]\n"
            ),
            Static("[#484848]agent vibe / personality[/]"),
            Input(
                placeholder="e.g. sharp, pragmatic, collaborative",
                id="input-agent-feel",
            ),
            Static("[#484848]biggest strengths (comma-separated)[/]"),
            Input(
                placeholder="e.g. debugging, architecture, research",
                id="input-agent-strengths",
            ),
            Static("[#484848]company roles (comma-separated)[/]"),
            Input(
                placeholder="e.g. frontend lead, backend lead, researcher, pm",
                id="input-agent-roles",
            ),
            Static("[#484848]number of generated workers (1-8)[/]"),
            Input(
                placeholder="3",
                value="3",
                id="input-agent-count",
            ),
            Static(
                "[#484848]or import your own AGENT.md file paths (comma-separated)[/]"
            ),
            Input(
                placeholder=(
                    "/path/to/frontend/AGENT.md, /path/to/researcher/AGENT.md"
                ),
                id="input-agent-imports",
            ),
            Static(
                "[#484848]\n  sessions/   conversations\n"
                "  memories/   persistent memory\n"
                "  tasks/      project tracking\n"
                "  agents/     identities\n"
                "  knowledge/  research[/]"
            ),
            Button("continue", classes="ob-btn"),
        ]

    # ── Step 3 — Connecting ───────────────────────────────────────────────

    def _connect_widgets(self) -> list:
        return [
            Static("[#cccccc]\n  setting up…\n[/]"),
            Static("  [#c2915e]·[/] preparing…", id="connect-log"),
            Vertical(id="connect-actions"),
        ]

    @work(exclusive=True, thread=False)
    async def _do_connect(self) -> None:
        """Background worker: test backend → init vault → load templates."""
        await asyncio.sleep(0.3)  # let widgets mount

        try:
            log_w = self.query_one("#connect-log", Static)
            actions = self.query_one("#connect-actions", Vertical)
        except Exception:
            return

        lines: list[str] = []

        def _log(text: str) -> None:
            lines.append(text)
            log_w.update("\n".join(lines))

        # 1 — Backend test
        _log(f"  [#c2915e]·[/] checking {self._provider}…")
        try:
            client = create_llm_client(
                provider=self._provider,
                backup_provider=self._backup_provider,
                perplexity_api_key=self._api_key,
                codex_command=self._codex_command,
                codex_model=self._codex_model,
                codex_timeout_seconds=self._codex_timeout_seconds,
                workspace_root=Path.cwd(),
                vault_path=self._vault_path or None,
            )
            ok = await client.ping()
        except Exception:
            ok = False
        finally:
            if "client" in locals():
                await client.close()

        if not ok:
            lines[-1] = f"  [#a05050]×[/] {self._provider} unavailable"
            log_w.update("\n".join(lines))
            await actions.mount_all([
                Static(""),
                Button("← Back", classes="ob-btn-back"),
            ])
            return

        lines[-1] = f"  [#7c9a6e]·[/] {self._provider} ready"
        log_w.update("\n".join(lines))
        await asyncio.sleep(0.2)

        # 2 — Vault
        _log("  [#c2915e]·[/] initializing vault…")
        from yui.obsidian.vault import ObsidianVault

        vault = ObsidianVault(self._vault_path)
        vault.ensure_structure()
        vault.write_welcome()
        vault.seed_instructions()
        lines[-1] = "  [#7c9a6e]·[/] vault ready"
        log_w.update("\n".join(lines))
        await asyncio.sleep(0.2)

        # 3 — Agent identities
        _log("  [#c2915e]·[/] loading agents…")
        templates = Path(__file__).parent.parent / "templates"
        agents_dir = Path(self._vault_path) / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        if templates.exists():
            for md in templates.glob("*.md"):
                if md.stem == "instructions":
                    continue
                agent_dir = agents_dir / md.stem
                agent_dir.mkdir(parents=True, exist_ok=True)
                dest = agent_dir / "AGENT.md"
                if not dest.exists():
                    shutil.copy2(md, dest)

        imported = 0
        if self._agent_import_paths:
            _log("  [#c2915e]·[/] importing AGENT.md files…")
            imported = self._import_custom_agents(agents_dir)
            lines[-1] = f"  [#7c9a6e]·[/] {imported} AGENT.md files imported"
            log_w.update("\n".join(lines))
            await asyncio.sleep(0.2)

        generated = 0
        if self._agent_feel or self._agent_strengths or self._agent_roles:
            _log("  [#c2915e]·[/] generating custom agents…")
            try:
                generated = await self._generate_custom_agents(agents_dir)
                lines[-1] = (
                    "  [#7c9a6e]·[/] "
                    f"{generated} custom agents generated"
                )
            except Exception:
                lines[-1] = "  [#a05050]×[/] custom generation skipped"
            log_w.update("\n".join(lines))
            await asyncio.sleep(0.2)

        count = self._count_agent_identities(agents_dir)
        lines[-1] = (
            f"  [#7c9a6e]·[/] {count} agents ready"
            if generated or imported
            else f"  [#7c9a6e]·[/] {count} agents loaded"
        )
        log_w.update("\n".join(lines))
        await asyncio.sleep(0.2)

        # 4 — Save config
        _log("  [#c2915e]·[/] saving config…")
        config = NexusConfig(
            provider=self._provider,
            backup_provider=self._backup_provider,
            perplexity_api_key=self._api_key,
            obsidian_vault_path=self._vault_path,
            codex_command=self._codex_command,
            codex_model=self._codex_model,
            codex_timeout_seconds=self._codex_timeout_seconds,
        )
        config.save()
        lines[-1] = "  [#7c9a6e]·[/] saved"
        _log("\n  [#7c9a6e]all systems ready.[/]")

        await actions.mount_all([
            Static(""),
            Button("Continue →", classes="ob-btn"),
        ])

    async def _generate_custom_agents(self, agents_dir: Path) -> int:
        """Generate custom worker identities from user onboarding inputs."""
        client = create_llm_client(
            provider=self._provider,
            backup_provider="none",
            perplexity_api_key=self._api_key,
            codex_command=self._codex_command,
            codex_model=self._codex_model,
            codex_timeout_seconds=self._codex_timeout_seconds,
            workspace_root=Path.cwd(),
            vault_path=agents_dir.parent,
        )
        try:
            desired_vibe = self._agent_feel or "balanced"
            desired_strengths = (
                self._agent_strengths
                or "research, planning, execution"
            )
            desired_roles = ", ".join(self._agent_roles) if self._agent_roles else ""
            desired_roles_line = (
                desired_roles
                if desired_roles
                else "not specified"
            )
            target_count = max(self._agent_count, len(self._agent_roles))
            prompt = (
                f"Generate exactly {target_count} worker agent identities for a "
                "multi-agent CLI company simulation.\n\n"
                f"Desired vibe/personality: {desired_vibe}\n"
                f"Desired strongest skills: {desired_strengths}\n\n"
                "Company roles (if provided, map one identity per role): "
                f"{desired_roles_line}\n\n"
                "Return ONLY valid JSON (no markdown), as an array of objects with keys:\n"
                "id, name, role, persona, skills, avatar, color, system_prompt\n\n"
                "Rules:\n"
                "- id should be lowercase-kebab-case\n"
                "- role should be concise and practical and distinct per agent\n"
                "- skills must be a list of 2-5 short tags\n"
                "- avatar one unicode symbol\n"
                "- color as #RRGGBB\n"
                "- system_prompt 4-10 lines, actionable (this is each agent's own instructions)\n"
                "- Do NOT generate an orchestrator\n"
            )
            raw = await client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You generate strict JSON for agent identity files. "
                            "Return JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=4096,
            )
        finally:
            await client.close()

        specs = self._parse_agent_specs(raw)
        created = 0
        target_count = max(self._agent_count, len(self._agent_roles))
        for i, spec in enumerate(specs[: target_count], start=1):
            agent_id = self._slug(spec.get("id") or spec.get("name") or f"worker-{i}")
            if not agent_id or agent_id == "orchestrator":
                agent_id = f"worker-{i}"
            agent_dir = agents_dir / agent_id
            file_path = agent_dir / "AGENT.md"
            suffix = 2
            while file_path.exists():
                agent_dir = agents_dir / f"{agent_id}-{suffix}"
                file_path = agent_dir / "AGENT.md"
                suffix += 1
            agent_dir.mkdir(parents=True, exist_ok=True)

            md = self._render_identity_markdown(spec, agent_id)
            file_path.write_text(md, encoding="utf-8")
            created += 1
        return created

    def _import_custom_agents(self, agents_dir: Path) -> int:
        """Import user-provided AGENT.md files into vault agents directory."""
        created = 0
        for idx, raw_path in enumerate(self._agent_import_paths, start=1):
            src = Path(raw_path).expanduser().resolve()
            if not src.exists() or not src.is_file():
                continue
            if src.suffix.lower() != ".md":
                continue
            base_id = src.parent.name if src.stem.lower() == "agent" else src.stem
            agent_id = self._slug(base_id) or f"imported-agent-{idx}"
            if agent_id == "orchestrator":
                agent_id = f"imported-agent-{idx}"

            agent_dir = agents_dir / agent_id
            dest = agent_dir / "AGENT.md"
            suffix = 2
            while dest.exists():
                agent_dir = agents_dir / f"{agent_id}-{suffix}"
                dest = agent_dir / "AGENT.md"
                suffix += 1

            agent_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            created += 1
        return created

    @staticmethod
    def _count_agent_identities(agents_dir: Path) -> int:
        """Count AGENT.md and legacy .md identity files."""
        seen: set[Path] = set()
        for p in agents_dir.rglob("*"):
            if p.is_file() and p.name.lower() == "agent.md":
                seen.add(p)
        for p in agents_dir.glob("*.md"):
            seen.add(p)
        return len(seen)

    def _parse_agent_specs(self, raw: str) -> list[dict]:
        """Parse a JSON array from model output."""
        text = raw.strip()

        code_block = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1).strip()

        if not text.startswith("["):
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except json.JSONDecodeError:
            return []
        return []

    @staticmethod
    def _slug(value: str) -> str:
        value = value.lower().strip()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        return value.strip("-")

    @staticmethod
    def _render_identity_markdown(spec: dict, agent_id: str) -> str:
        """Render generated agent spec to AGENT.md format."""
        name = str(spec.get("name") or agent_id.title())
        role = str(spec.get("role") or "Worker")
        persona = str(spec.get("persona") or "Practical and focused.")
        avatar = str(spec.get("avatar") or "●")[:2]
        color = str(spec.get("color") or "#8b7ec8")
        skills = spec.get("skills") or []
        if not isinstance(skills, list):
            skills = []
        skills = [str(s).strip() for s in skills if str(s).strip()][:5]
        system_prompt = str(
            spec.get("system_prompt")
            or "Work clearly, communicate succinctly, and deliver results."
        ).strip()

        skill_lines = "\n".join(f"  - {s}" for s in skills) or "  - execution"
        return (
            "---\n"
            f"id: {agent_id}\n"
            f"name: {name}\n"
            f"role: {role}\n"
            "persona: >\n"
            f"  {persona}\n"
            "skills:\n"
            f"{skill_lines}\n"
            f'avatar: "{avatar}"\n'
            f'color: "{color}"\n'
            "---\n\n"
            f"# {name} Identity\n\n"
            f"{system_prompt}\n"
        )

    # ── Step 4 — Ready ────────────────────────────────────────────────────

    def _ready_widgets(self) -> list:
        return [
            Static("[#7c9a6e]ready.[/]\n"),
            Static(
                "  [#cccccc]type[/]         [#6b6b6b]talk to the orchestrator[/]\n"
                "  [#8b7ec8]/research[/]   [#6b6b6b]search the web[/]\n"
                "  [#8b7ec8]/task[/]       [#6b6b6b]create a task[/]\n"
                "  [#8b7ec8]/model[/]      [#6b6b6b]switch models[/]\n"
                "  [#8b7ec8]/settings[/]   [#6b6b6b]configure[/]\n"
                "  [#8b7ec8]/help[/]       [#6b6b6b]all commands[/]\n"
            ),
            Button("enter yui", id="btn-launch", classes="ob-btn"),
        ]

    # ── Navigation ────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        classes = event.button.classes

        # Back button
        if "ob-btn-back" in classes:
            self._step = max(self._step - 1, 0)
            self._show_step()
            return

        # Launch button
        if btn_id == "btn-launch":
            config = NexusConfig.load()
            self.app.pop_screen()
            from yui.tui.app import NexusApp
            if isinstance(self.app, NexusApp):
                self.app.initialize_engine(config)
            return

        # Forward / continue buttons (ob-btn class, not back, not launch)
        if "ob-btn" in classes:
            # Validate before advancing
            if self._step == 1:
                try:
                    provider = self.query_one("#input-provider", Input).value.strip().lower()
                    backup = self.query_one(
                        "#input-backup-provider", Input,
                    ).value.strip().lower()
                    api_key = self.query_one("#input-api-key", Input).value.strip()
                    codex_command = self.query_one(
                        "#input-codex-command", Input,
                    ).value.strip()
                    codex_model = self.query_one(
                        "#input-codex-model", Input,
                    ).value.strip()
                    codex_timeout = self.query_one(
                        "#input-codex-timeout", Input,
                    ).value.strip()
                except Exception:
                    return
                if provider not in ("perplexity", "codex"):
                    return
                if backup not in ("", "none", "perplexity", "codex"):
                    return
                if "perplexity" in (provider, backup or "none") and not api_key:
                    return
                self._provider = provider
                self._backup_provider = backup or "none"
                if self._backup_provider == self._provider:
                    self._backup_provider = "none"
                self._api_key = api_key
                self._codex_command = codex_command or "codex"
                self._codex_model = codex_model or "gpt-5.4"
                try:
                    self._codex_timeout_seconds = max(30, int(codex_timeout or "60"))
                except ValueError:
                    self._codex_timeout_seconds = 60
            elif self._step == 2:
                try:
                    val = self.query_one("#input-vault-path", Input).value.strip()
                except Exception:
                    return
                if not val:
                    return
                self._vault_path = str(Path(val).expanduser().resolve())
                try:
                    self._agent_feel = self.query_one(
                        "#input-agent-feel", Input,
                    ).value.strip()
                    self._agent_strengths = self.query_one(
                        "#input-agent-strengths", Input,
                    ).value.strip()
                    roles_raw = self.query_one(
                        "#input-agent-roles", Input,
                    ).value.strip()
                    self._agent_roles = [
                        r.strip() for r in roles_raw.split(",") if r.strip()
                    ]
                    count_raw = self.query_one(
                        "#input-agent-count", Input,
                    ).value.strip()
                    count = int(count_raw or "3")
                    self._agent_count = max(1, min(8, count))
                    imports_raw = self.query_one(
                        "#input-agent-imports", Input,
                    ).value.strip()
                    self._agent_import_paths = [
                        p.strip() for p in imports_raw.split(",") if p.strip()
                    ]
                except Exception:
                    self._agent_count = 3
                    self._agent_roles = []
                    self._agent_import_paths = []

            self._step = min(self._step + 1, 4)
            self._show_step()
