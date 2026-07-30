"""Persistent channel store — every message survives restarts.

Messages are appended to per-channel markdown files under ``channels/``.
On channel switch the full history is loaded from disk.  The context
engine searches these files like any vault note — agents never receive
the raw dump, only what the search deems relevant.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from yui import Message
from yui.obsidian.vault import ObsidianVault

log = logging.getLogger("yui.channels")

_HEADER = "---\ntype: channel\n---\n"
_SAFE_CHANNEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ChannelStore:
    """Vault-backed persistent message history per channel."""

    DEFAULT_CHANNELS = ("general", "research", "tasks", "logs")

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault
        self._ensure_channels()

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def _ensure_channels(self) -> None:
        """Create channel files for defaults if they don't exist."""
        for ch in self.DEFAULT_CHANNELS:
            self.create_channel(ch)

    # ── Write ─────────────────────────────────────────────────────────────

    def append(self, message: Message) -> None:
        """Persist a single message to its channel file."""
        rel = self._channel_rel(message.channel)
        ts = message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"\n**{message.sender}** · {ts}\n"
            f"{message.content}\n"
        )
        if not self.vault.note_exists(rel):
            self.vault.write_note(rel, _HEADER)
        self.vault.append_to_note(rel, line)

    # ── Read ──────────────────────────────────────────────────────────────

    def load(self, channel: str, limit: int = 200) -> list[Message]:
        """Load persisted messages for a channel. Returns most recent *limit*."""
        rel = self._channel_rel(channel)
        full = self.vault.resolve_path(rel)
        if not full.exists():
            return []

        text = full.read_text(encoding="utf-8")
        # Strip YAML front-matter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                text = text[end + 3:]

        messages: list[Message] = []
        blocks = text.split("\n**")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            # Parse "sender** · timestamp\ncontent"
            try:
                if not block.startswith("**"):
                    block = "**" + block
                # Extract sender
                sender_end = block.index("**", 2)
                sender = block[2:sender_end]
                rest = block[sender_end + 2:].strip()
                # Extract timestamp
                if rest.startswith("·"):
                    rest = rest[1:].strip()
                ts_end = rest.index("\n") if "\n" in rest else len(rest)
                ts_str = rest[:ts_end].strip()
                content = rest[ts_end:].strip()
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    ts = datetime.now()
                messages.append(Message(
                    sender=sender,
                    content=content,
                    channel=channel,
                    timestamp=ts,
                ))
            except (ValueError, IndexError):
                continue

        return messages[-limit:]

    # ── Query ─────────────────────────────────────────────────────────────

    def list_channels(self) -> list[str]:
        """Return all channel names that have files."""
        channels_dir = self.vault.resolve_path("channels")
        if not channels_dir.exists():
            return list(self.DEFAULT_CHANNELS)
        names = [p.stem for p in channels_dir.glob("*.md") if _SAFE_CHANNEL.fullmatch(p.stem)]
        return sorted(set(names) | set(self.DEFAULT_CHANNELS))

    def create_channel(self, name: str) -> None:
        """Create a new channel file."""
        rel = self._channel_rel(name)
        if not self.vault.note_exists(rel):
            self.vault.write_note(rel, _HEADER)

    def clear(self, channel: str) -> None:
        """Wipe a channel's message history (keeps the file)."""
        rel = self._channel_rel(channel)
        if self.vault.note_exists(rel):
            self.vault.write_note(rel, _HEADER)

    @staticmethod
    def _channel_rel(channel: str) -> str:
        if not _SAFE_CHANNEL.fullmatch(channel):
            raise ValueError("Invalid channel name; use letters, numbers, dashes, or underscores.")
        return f"channels/{channel}.md"
