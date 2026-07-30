"""Low-level Obsidian vault operations (read / write / list / delete)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_WELCOME_NOTE = """\
# Welcome to Yui Daily

Yui is a calm, local-first place to plan a day. Your tasks stay here as
plain Markdown, so they remain readable in Obsidian and easy to back up.

## Structure

| Folder | Purpose |
|--------|--------|
| `tasks/` | To-dos, schedule, duration, area, and completion history |
| `knowledge/` | Notes and reference material |
| `sessions/` | Legacy activity history |
| `memories/` | Legacy saved context |
| `logs/` | System events |

## Quick capture

Type a title and add optional tokens: `@09:30`, `/30m`, `#work`, `!high`,
`today`, `tomorrow`, or `~2026-08-01`. Yui writes the result immediately.
"""


class ObsidianVault:
    """Manages the on-disk Obsidian vault that backs all Yui knowledge."""

    REQUIRED_DIRS = (
        "sessions",
        "memories",
        "tasks",
        "agents",
        "knowledge",
        "logs",
        "channels",
    )

    def __init__(self, vault_path: str | Path) -> None:
        self.root = Path(vault_path).expanduser().resolve()

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def ensure_structure(self) -> None:
        """Create the required vault skeleton if it doesn't exist yet."""
        self.root.mkdir(parents=True, exist_ok=True)
        for dirname in self.REQUIRED_DIRS:
            (self.root / dirname).mkdir(exist_ok=True)
        # .obsidian folder so Obsidian recognises it
        (self.root / ".obsidian").mkdir(exist_ok=True)

    def write_welcome(self) -> None:
        """Seed a getting-started note on first init."""
        if self.note_exists("knowledge/welcome.md"):
            return
        self.write_note(
            "knowledge/welcome.md",
            _WELCOME_NOTE,
            frontmatter={"type": "guide", "title": "Welcome to Yui"},
        )

    def seed_instructions(self) -> None:
        """Copy default instructions.md into the vault if it doesn't exist."""
        if self.note_exists("instructions.md"):
            return
        template = Path(__file__).parent.parent / "templates" / "instructions.md"
        if template.exists():
            content = template.read_text("utf-8")
            self.write_note("instructions.md", content)

    def read_instructions(self) -> str:
        """Read the vault-level instructions.md, return empty if missing."""
        path = self.root / "instructions.md"
        if not path.exists():
            return ""
        return path.read_text("utf-8")

    # ── CRUD ──────────────────────────────────────────────────────────────

    def read_note(self, rel_path: str) -> tuple[dict, str]:
        """Return *(frontmatter_dict, body_text)* for a note."""
        full = self._resolve_path(rel_path)
        if not full.exists():
            return {}, ""
        return self._parse_frontmatter(full.read_text("utf-8"))

    def write_note(
        self,
        rel_path: str,
        content: str,
        frontmatter: dict | None = None,
    ) -> Path:
        """Write a markdown note.  Creates parent dirs as needed."""
        full = self._resolve_path(rel_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        parts: list[str] = []
        if frontmatter:
            parts.append("---")
            parts.append(yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).rstrip())
            parts.append("---\n")
        parts.append(content)
        full.write_text("\n".join(parts), "utf-8")
        return full

    def append_to_note(self, rel_path: str, content: str) -> None:
        full = self._resolve_path(rel_path)
        if full.exists():
            full.write_text(full.read_text("utf-8") + "\n" + content, "utf-8")
        else:
            self.write_note(rel_path, content)

    def delete_note(self, rel_path: str) -> bool:
        full = self._resolve_path(rel_path)
        if full.exists():
            full.unlink()
            return True
        return False

    def note_exists(self, rel_path: str) -> bool:
        return self._resolve_path(rel_path).exists()

    # ── Listing ───────────────────────────────────────────────────────────

    def list_notes(self, folder: str = "", pattern: str = "*.md") -> list[str]:
        """Return relative paths of all matching notes under *folder*."""
        base = self._resolve_path(folder, allow_root=True)
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(self.root)) for p in base.rglob(pattern)
        )

    def list_dirs(self, folder: str = "") -> list[str]:
        base = self._resolve_path(folder, allow_root=True)
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in base.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def resolve_path(self, rel_path: str, *, allow_root: bool = False) -> Path:
        """Return a contained absolute path for stores that need raw file access."""
        return self._resolve_path(rel_path, allow_root=allow_root)

    def _resolve_path(self, rel_path: str, *, allow_root: bool = False) -> Path:
        """Resolve a relative path and reject any escape from the vault root."""
        root = self.root.expanduser().resolve()
        candidate = (root / rel_path).resolve()
        if candidate == root:
            if allow_root:
                return candidate
            raise ValueError("A note path must point to a file inside the vault.")
        if root not in candidate.parents:
            raise ValueError("Path escapes the configured vault root.")
        return candidate

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        m = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
        if m:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                fm = {}
            return fm, m.group(2).strip()
        return {}, text.strip()
