"""Mem0-style memory system backed by Obsidian markdown files."""

from __future__ import annotations

import math
from datetime import timedelta

from yui import MemoryEntry, _uid
from yui.obsidian.search import ObsidianSearch
from yui.obsidian.vault import ObsidianVault
from yui.time_utils import aware_now, parse_datetime


class MemoryStore:
    """Persistent, searchable, decaying memory — like Mem0 on files."""

    FOLDER = "memories"

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault
        self.search = ObsidianSearch(vault.root)

    # ── Write ─────────────────────────────────────────────────────────────

    def add(
        self,
        content: str,
        tags: list[str] | None = None,
        importance: float = 0.5,
        source: str = "",
    ) -> MemoryEntry:
        """Store a new memory."""
        mem = MemoryEntry(
            content=content,
            tags=tags or [],
            importance=max(0.0, min(1.0, importance)),
            source=source,
        )
        tag_line = " ".join(f"#{t}" for t in mem.tags) if mem.tags else ""
        body = (
            f"{mem.content}\n\n"
            f"{tag_line}\n"
        )
        self.vault.write_note(
            f"{self.FOLDER}/{mem.id}.md",
            body,
            frontmatter=self._to_frontmatter(mem),
        )
        return mem

    # ── Read / Search ─────────────────────────────────────────────────────

    def recall(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Search memories by relevance, boosted by importance & recency."""
        results = self.search.search(query, folder=self.FOLDER, max_results=top_k * 2)
        memories: list[MemoryEntry] = []
        for r in results:
            fm, body = self.vault.read_note(r.path)
            if not fm:
                continue
            mem = self._from_frontmatter(fm, body)
            # Recency boost
            hours_ago = (aware_now() - mem.accessed).total_seconds() / 3600
            recency = math.exp(-hours_ago / 168)  # 1-week half-life
            mem.importance = mem.importance * 0.6 + recency * 0.2 + (r.score / 50) * 0.2
            memories.append(mem)
        memories.sort(key=lambda m: m.importance, reverse=True)
        # Touch accessed timestamp for returned memories
        for mem in memories[:top_k]:
            self._touch(mem)
        return memories[:top_k]

    def get_all(self) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for note in self.vault.list_notes(self.FOLDER):
            fm, body = self.vault.read_note(note)
            if fm:
                entries.append(self._from_frontmatter(fm, body))
        return entries

    # ── Update / Delete ───────────────────────────────────────────────────

    def forget(self, memory_id: str) -> bool:
        return self.vault.delete_note(f"{self.FOLDER}/{memory_id}.md")

    def decay(self, max_age_hours: int = 72) -> int:
        """Delete memories older than *max_age_hours* with low importance."""
        cutoff = aware_now() - timedelta(hours=max_age_hours)
        removed = 0
        for note in self.vault.list_notes(self.FOLDER):
            fm, _ = self.vault.read_note(note)
            if not fm:
                continue
            accessed = parse_datetime(fm.get("accessed", fm.get("created", "")))
            importance = float(fm.get("importance", 0.5))
            if accessed < cutoff and importance < 0.3:
                self.vault.delete_note(note)
                removed += 1
        return removed

    def consolidate(self) -> int:
        """Merge duplicate / near-duplicate memories (stub for v1)."""
        # Future: use embedding similarity to merge related memories
        return 0

    # ── Private ───────────────────────────────────────────────────────────

    def _touch(self, mem: MemoryEntry) -> None:
        path = f"{self.FOLDER}/{mem.id}.md"
        if not self.vault.note_exists(path):
            return
        fm, body = self.vault.read_note(path)
        fm["accessed"] = aware_now().isoformat()
        fm["access_count"] = fm.get("access_count", 0) + 1
        self.vault.write_note(path, body, frontmatter=fm)

    @staticmethod
    def _to_frontmatter(mem: MemoryEntry) -> dict:
        return {
            "id": mem.id,
            "importance": round(mem.importance, 3),
            "tags": mem.tags,
            "source": mem.source,
            "created": mem.created.isoformat(),
            "accessed": mem.accessed.isoformat(),
            "access_count": mem.access_count,
        }

    @staticmethod
    def _from_frontmatter(fm: dict, body: str) -> MemoryEntry:
        return MemoryEntry(
            id=fm.get("id", _uid()),
            content=body.strip(),
            tags=fm.get("tags", []),
            importance=float(fm.get("importance", 0.5)),
            source=fm.get("source", ""),
            created=parse_datetime(fm.get("created")),
            accessed=parse_datetime(fm.get("accessed", fm.get("created"))),
            access_count=int(fm.get("access_count", 0)),
        )
