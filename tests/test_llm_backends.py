"""Tests for provider selection and backup LLM behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from yui.config import NexusConfig
from yui.core.llm import (
    CODEX_MINIMAL_OVERRIDES,
    BackupLLMClient,
    BaseLLMClient,
    CodexCLIClient,
    create_llm_client,
)


class DummyClient(BaseLLMClient):
    """Small fake backend for backup-flow tests."""

    def __init__(self, *, fail: bool, response: str) -> None:
        super().__init__(model="dummy", research_model="dummy")
        self.fail = fail
        self.response = response

    async def chat(self, messages, model=None, temperature=None, max_tokens=None, tools=None):
        if self.fail:
            raise RuntimeError("primary failed")
        return self.response

    async def research(
        self,
        query,
        system="Be precise and comprehensive. Cite sources.",
        model=None,
    ):
        if self.fail:
            raise RuntimeError("primary failed")
        return self.response

    async def search(self, query, max_results=10, country=""):
        if self.fail:
            raise RuntimeError("primary failed")
        return [{"title": self.response, "url": "https://example.com", "snippet": query}]

    async def ping(self) -> bool:
        return not self.fail


def test_config_allows_codex_without_perplexity_key() -> None:
    """Codex mode should be considered configured with only a vault path."""
    config = NexusConfig(provider="codex", obsidian_vault_path="/tmp/yui-vault")
    assert config.is_configured() is True


def test_create_llm_client_builds_codex_backend() -> None:
    """Factory should return the Codex backend when requested."""
    client = create_llm_client(
        provider="codex",
        codex_command="codex",
        codex_model="gpt-5.4-mini",
        codex_timeout_seconds=123,
        workspace_root="/tmp",
        vault_path="/tmp/vault",
    )
    assert isinstance(client, CodexCLIClient)
    assert client.model == "gpt-5.4-mini"
    assert client.timeout_seconds == 123
    assert client.workspace_root == Path("/tmp").resolve()
    assert client.vault_path == Path("/tmp/vault").resolve()


@pytest.mark.asyncio
async def test_backup_client_uses_backup_when_primary_fails() -> None:
    """Fallback wrapper should return the backup result after a primary failure."""
    primary = DummyClient(fail=True, response="primary")
    backup = DummyClient(fail=False, response="backup")
    client = BackupLLMClient(primary, backup)

    result = await client.chat([{"role": "user", "content": "hello"}])

    assert result == "backup"


def test_codex_command_builder_adds_search_and_vault(monkeypatch) -> None:
    """Codex command construction should include workspace, output, and vault access."""
    client = CodexCLIClient(
        command="codex",
        model="gpt-5.4",
        workspace_root="/tmp/workspace",
        vault_path="/tmp/vault",
    )
    monkeypatch.setattr(client, "_resolve_command", lambda: "/usr/local/bin/codex")

    cmd = client._build_command(
        output_file=Path("/tmp/out.txt"),
        model="gpt-5.4",
        enable_search=True,
    )

    assert cmd[:2] == ["/usr/local/bin/codex", "--search"]
    exec_index = cmd.index("exec")
    assert exec_index > 2
    assert cmd[exec_index:exec_index + 2] == ["exec", "--skip-git-repo-check"]
    for override in CODEX_MINIMAL_OVERRIDES:
        marker = ["-c", override]
        assert marker in [cmd[i:i + 2] for i in range(len(cmd) - 1)]
    expected_vault = str(Path("/tmp/vault").resolve())
    assert ["--add-dir", expected_vault] == cmd[
        cmd.index("--add-dir"):cmd.index("--add-dir") + 2
    ]
    assert cmd[-1] == "-"


def test_codex_failure_classifier_reports_network_error() -> None:
    """Known Codex transport errors should be surfaced as network failures."""
    message = CodexCLIClient._classify_codex_failure(
        "failed to lookup address information: nodename nor servname provided"
    )

    assert message is not None
    assert "could not reach OpenAI endpoints" in message
