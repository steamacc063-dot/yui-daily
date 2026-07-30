"""Security regressions for local files, config secrets, and legacy agents."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

import yui.config as config_module
from yui import Message
from yui.config import NexusConfig
from yui.core.agent import resolve_identity_candidates
from yui.obsidian.channels import ChannelStore
from yui.obsidian.tasks import TaskTracker
from yui.obsidian.vault import ObsidianVault


def test_vault_rejects_paths_that_escape_its_root(tmp_path: Path) -> None:
    vault = ObsidianVault(tmp_path / "vault")
    vault.ensure_structure()

    with pytest.raises(ValueError, match="vault"):
        vault.write_note("../escape.md", "must not be written")

    assert not (tmp_path / "escape.md").exists()


def test_task_tracker_skips_malicious_frontmatter_ids(tmp_path: Path) -> None:
    vault = ObsidianVault(tmp_path / "vault")
    vault.ensure_structure()
    tracker = TaskTracker(vault)
    vault.write_note(
        "tasks/poisoned.md",
        "# Poisoned",
        frontmatter={"id": "../../outside", "title": "Poisoned", "status": "todo"},
    )

    assert tracker.list_all() == []
    with pytest.raises(ValueError, match="task id"):
        tracker.get("../../outside")


def test_config_file_is_written_with_owner_only_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / ".yui"
    config_file = config_dir / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)

    NexusConfig(perplexity_api_key="secret").save()

    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600


def test_legacy_config_migration_copies_only_productivity_preferences(
    tmp_path: Path,
) -> None:
    old_dir = tmp_path / ".nexus"
    old_file = old_dir / "config.yaml"
    new_file = tmp_path / ".yui" / "config.yaml"
    old_dir.mkdir()
    old_file.write_text(
        "obsidian_vault_path: /notes\n"
        "theme: textual-dark\n"
        "imported_themes:\n  - quiet\n"
        "perplexity_api_key: do-not-copy\n",
        encoding="utf-8",
    )
    (old_dir / "unrelated-secret.txt").write_text("do-not-copy", encoding="utf-8")

    config_module.migrate_legacy_config(old_file, new_file)

    migrated = new_file.read_text("utf-8")
    assert "obsidian_vault_path: /notes" in migrated
    assert "theme: textual-dark" in migrated
    assert "quiet" in migrated
    assert "perplexity_api_key" not in migrated
    assert "do-not-copy" not in migrated
    assert not (new_file.parent / "unrelated-secret.txt").exists()
    assert stat.S_IMODE(new_file.stat().st_mode) == 0o600


def test_legacy_agent_identity_resolution_stays_inside_agents_root(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"

    candidates = resolve_identity_candidates(agents_root, "writer")

    assert candidates
    assert all(agents_root.resolve() in candidate.parents for candidate in candidates)
    with pytest.raises(ValueError, match="identity"):
        resolve_identity_candidates(agents_root, "../../.ssh/config")


def test_channel_names_cannot_escape_the_vault(tmp_path: Path) -> None:
    vault = ObsidianVault(tmp_path / "vault")
    vault.ensure_structure()
    channels = ChannelStore(vault)

    with pytest.raises(ValueError, match="channel"):
        channels.append(Message(sender="test", content="nope", channel="../../outside"))
    with pytest.raises(ValueError, match="channel"):
        channels.create_channel("../outside")

    assert not (tmp_path / "outside.md").exists()
