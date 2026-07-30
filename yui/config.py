"""Configuration management — persisted in ~/.yui/config.yaml."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".yui"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

_OLD_CONFIG_DIR = Path.home() / ".nexus"
_OLD_CONFIG_FILE = _OLD_CONFIG_DIR / "config.yaml"
_LEGACY_PREFERENCE_FIELDS = frozenset(
    {"obsidian_vault_path", "theme", "imported_themes"}
)


def _write_secure_yaml(path: Path, values: dict[str, object]) -> None:
    """Write YAML with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
        yaml.safe_dump(values, fh, default_flow_style=False, sort_keys=False)


def migrate_legacy_config(old_file: Path, new_file: Path) -> None:
    """Migrate only non-secret productivity preferences from legacy Nexus."""
    if new_file.exists() or not old_file.is_file():
        return
    try:
        raw = yaml.safe_load(old_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return
    if not isinstance(raw, dict):
        return

    preferences = {
        key: raw[key]
        for key in _LEGACY_PREFERENCE_FIELDS
        if key in raw
        and (
            isinstance(raw[key], str)
            or (
                key == "imported_themes"
                and isinstance(raw[key], list)
                and all(isinstance(item, str) for item in raw[key])
            )
        )
    }
    if preferences:
        _write_secure_yaml(new_file, preferences)


migrate_legacy_config(_OLD_CONFIG_FILE, CONFIG_FILE)
if CONFIG_FILE.exists():
    CONFIG_FILE.chmod(0o600)


@dataclass
class NexusConfig:
    provider: str = "perplexity"
    backup_provider: str = "none"
    perplexity_api_key: str = ""
    obsidian_vault_path: str = ""
    model: str = "perplexity/sonar"
    research_model: str = "sonar-reasoning-pro"
    codex_command: str = "codex"
    codex_model: str = "gpt-5.4"
    codex_timeout_seconds: int = 60
    orchestrator_identity: str = ""
    workers_dir: str = ""
    theme: str = "textual-dark"
    imported_themes: list[str] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)
    # Generation
    temperature: float = 0.4
    max_output_tokens: int = 16384
    reasoning: str = "high"  # off | low | medium | high
    # Tools
    web_search: bool = True
    fetch_url: bool = True
    search_recency_filter: str = "none"  # day | week | month | year | none
    # Context
    auto_research: bool = True
    max_context_tokens: int = 32000
    memory_decay_hours: int = 72

    # ── Persistence ───────────────────────────────────────────────────────

    @classmethod
    def load(cls) -> NexusConfig:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            known = {k: raw[k] for k in raw if k in cls.__dataclass_fields__}
            return cls(**known)
        return cls()

    def save(self) -> None:
        _write_secure_yaml(CONFIG_FILE, asdict(self))

    # ── Helpers ───────────────────────────────────────────────────────────

    @property
    def vault(self) -> Path:
        return Path(self.obsidian_vault_path)

    def is_configured(self) -> bool:
        if not self.obsidian_vault_path:
            return False
        if self.provider == "codex":
            return True
        return bool(self.perplexity_api_key)

    def identities_dir(self) -> Path:
        """Directory containing worker identity.md files."""
        if self.workers_dir:
            return Path(self.workers_dir)
        return self.vault / "agents"
