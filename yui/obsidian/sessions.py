"""Session file management — every conversation is persisted to Obsidian."""

from __future__ import annotations

from datetime import datetime

from yui import _uid
from yui.obsidian.vault import ObsidianVault


class SessionManager:
    """Creates and appends to per-session markdown files under ``sessions/``."""

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def create_session(self, title: str = "") -> str:
        """Start a new session, returns its ID."""
        sid = _uid()
        ts = datetime.now()
        name = title or f"session-{ts:%Y%m%d-%H%M}"
        rel = f"sessions/{name}-{sid}.md"
        self.vault.write_note(
            rel,
            f"# {name}\n\nStarted: {ts:%Y-%m-%d %H:%M:%S}\n\n---\n",
            frontmatter={
                "id": sid,
                "title": name,
                "created": ts.isoformat(),
                "status": "active",
            },
        )
        return sid

    # ── Messages ──────────────────────────────────────────────────────────

    def append_message(
        self,
        session_id: str,
        role: str,
        agent: str,
        content: str,
    ) -> None:
        """Append a chat turn to the session file."""
        path = self._find_session(session_id)
        if not path:
            return
        ts = datetime.now()
        block = (
            f"\n### {agent} ({role}) — {ts:%H:%M:%S}\n\n"
            f"{content}\n\n---\n"
        )
        self.vault.append_to_note(path, block)

    # ── Queries ───────────────────────────────────────────────────────────

    def get_session_text(self, session_id: str) -> str:
        path = self._find_session(session_id)
        if not path:
            return ""
        _, body = self.vault.read_note(path)
        return body

    def list_sessions(self) -> list[dict]:
        """Return metadata dicts for every session file."""
        sessions: list[dict] = []
        for note in self.vault.list_notes("sessions"):
            fm, _ = self.vault.read_note(note)
            if fm:
                fm["_path"] = note
                sessions.append(fm)
        return sessions

    def close_session(self, session_id: str) -> None:
        path = self._find_session(session_id)
        if not path:
            return
        fm, body = self.vault.read_note(path)
        fm["status"] = "closed"
        fm["closed"] = datetime.now().isoformat()
        self.vault.write_note(path, body, frontmatter=fm)

    # ── Internal ──────────────────────────────────────────────────────────

    def _find_session(self, session_id: str) -> str | None:
        for note in self.vault.list_notes("sessions"):
            if session_id in note:
                return note
        return None
