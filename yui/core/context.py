"""Context Intelligence Engine — smart context window management.

Core idea: agents don't carry the full history. They search Obsidian
for what's relevant, load it into a working context, and forget it when
it's no longer needed. This is the bridge between ephemeral LLM context
and persistent Obsidian knowledge.

Key principles:
  1. ADDITIVE loading — search results ADD to context, never replace.
  2. SELECTIVE forgetting — agents (or auto-prune) drop specific items.
  3. TURN TRACKING — every item knows when it was loaded and last used.
  4. SMART PRUNING — stale, low-relevance items are dropped first.
  5. ON-DEMAND LOADING — load any session, any note, any memory.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from yui.obsidian.memory import MemoryStore
from yui.obsidian.search import ObsidianSearch
from yui.obsidian.sessions import SessionManager
from yui.obsidian.vault import ObsidianVault

log = logging.getLogger("yui.context")

# After this many turns without being referenced, an item is considered stale
STALE_TURNS = 6
WORKSPACE_SCAN_EXTS = {
    ".md", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg",
}
WORKSPACE_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".cache", ".ruff_cache", ".pytest_cache",
}


@dataclass
class ContextItem:
    """A single unit of context loaded into an agent's working memory."""

    source: str  # "search" | "memory" | "session" | "note" | "task" | "identity"
    content: str
    relevance: float = 1.0
    path: str = ""
    loaded_at: datetime = field(default_factory=datetime.now)
    turn_loaded: int = 0
    last_referenced: int = 0
    pinned: bool = False


class ContextEngine:
    """Manages per-agent context windows with Obsidian-backed retrieval."""

    def __init__(
        self,
        vault: ObsidianVault,
        sessions: SessionManager,
        memory: MemoryStore,
        max_tokens: int = 32000,
    ) -> None:
        self.vault = vault
        self.search = ObsidianSearch(vault.root)
        self.sessions = sessions
        self.memory = memory
        self.max_tokens = max_tokens
        self._active: dict[str, list[ContextItem]] = defaultdict(list)
        self._turns: dict[str, int] = defaultdict(int)
        self.workspace_root = Path.cwd()

    @property
    def turn(self) -> dict[str, int]:
        return self._turns

    def _next_turn(self, agent_id: str) -> int:
        self._turns[agent_id] += 1
        return self._turns[agent_id]

    def begin_turn(self, agent_id: str) -> int:
        """Advance and return the turn counter for an agent."""
        return self._next_turn(agent_id)

    # ══════════════════════════════════════════════════════════════════════
    #  LOADING — all methods are ADDITIVE (they never wipe existing items)
    # ══════════════════════════════════════════════════════════════════════

    def search_and_load(
        self,
        agent_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[ContextItem]:
        """Search vault + memories and ADD results to active context.

        Unlike the old ``get_relevant`` this never replaces existing items.
        Duplicates (same path) are skipped; existing items get their
        ``last_referenced`` bumped instead.
        """
        turn = self._turns.get(agent_id, 0)
        existing_paths = {
            c.path for c in self._active.get(agent_id, []) if c.path
        }
        new_items: list[ContextItem] = []

        # 1. Vault full-text search
        vault_hits = self.search.search(query, max_results=top_k)
        for hit in vault_hits:
            if hit.path in existing_paths:
                self._touch(agent_id, hit.path, turn)
                continue
            new_items.append(ContextItem(
                source="search",
                content=hit.snippet,
                relevance=hit.score,
                path=hit.path,
                turn_loaded=turn,
                last_referenced=turn,
            ))

        # 2. Memory search
        memories = self.memory.recall(query, top_k=top_k)
        for mem in memories:
            mem_path = f"memories/{mem.id}.md"
            if mem_path in existing_paths:
                self._touch(agent_id, mem_path, turn)
                continue
            new_items.append(ContextItem(
                source="memory",
                content=mem.content,
                relevance=mem.importance,
                path=mem_path,
                turn_loaded=turn,
                last_referenced=turn,
            ))

        # 3. Workspace fallback (when vault+memory have no useful hit)
        if not new_items:
            for item in self._search_workspace(query, top_k=min(top_k, 3), turn=turn):
                if item.path in existing_paths:
                    self._touch(agent_id, item.path, turn)
                    continue
                new_items.append(item)

        # Deduplicate by content prefix, sort by relevance
        seen: set[str] = set()
        unique: list[ContextItem] = []
        for item in sorted(new_items, key=lambda c: c.relevance, reverse=True):
            key = item.content[:100]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        # Append to active (additive)
        added = unique[:top_k]
        self._active.setdefault(agent_id, []).extend(added)
        return added

    def load_note(self, agent_id: str, rel_path: str) -> ContextItem | None:
        """Load a specific vault note into active context by path."""
        turn = self._turns.get(agent_id, 0)

        # If already loaded, just bump last_referenced
        for item in self._active.get(agent_id, []):
            if item.path == rel_path:
                item.last_referenced = turn
                return item

        fm, body = self.vault.read_note(rel_path)
        if not body:
            return None

        # Truncate very large notes to fit budget
        max_chars = self.max_tokens * 2  # ~half the budget max per note
        if len(body) > max_chars:
            body = body[:max_chars] + "\n\n… (truncated)"

        item = ContextItem(
            source="note",
            content=body,
            relevance=5.0,
            path=rel_path,
            turn_loaded=turn,
            last_referenced=turn,
        )
        self._active.setdefault(agent_id, []).append(item)
        return item

    def load_session(
        self,
        agent_id: str,
        session_id: str,
    ) -> ContextItem | None:
        """Load a past session's content into active context."""
        turn = self._turns.get(agent_id, 0)

        # Check if already loaded
        session_path = f"session:{session_id}"
        for item in self._active.get(agent_id, []):
            if item.path == session_path:
                item.last_referenced = turn
                return item

        text = self.sessions.get_session_text(session_id)
        if not text:
            return None

        max_chars = self.max_tokens * 2
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n… (truncated)"

        item = ContextItem(
            source="session",
            content=text,
            relevance=5.0,
            path=session_path,
            turn_loaded=turn,
            last_referenced=turn,
        )
        self._active.setdefault(agent_id, []).append(item)
        return item

    def load_sessions_by_query(
        self,
        agent_id: str,
        query: str,
        max_sessions: int = 3,
    ) -> list[ContextItem]:
        """Search across all sessions and load matching ones."""
        hits = self.search.search(query, folder="sessions", max_results=max_sessions)
        loaded: list[ContextItem] = []
        for hit in hits:
            item = self.load_note(agent_id, hit.path)
            if item:
                loaded.append(item)
        return loaded

    def inject(self, agent_id: str, item: ContextItem) -> None:
        """Manually inject a context item (e.g., an identity doc)."""
        self._active.setdefault(agent_id, []).insert(0, item)

    # ══════════════════════════════════════════════════════════════════════
    #  FORGETTING — selective, smart, or total
    # ══════════════════════════════════════════════════════════════════════

    def forget(self, agent_id: str, path: str | None = None) -> int:
        """Remove items from active context.

        - path=None → flush ALL (agent completely forgets).
        - path="stale" → drop stale items.
        - path="source:<name>" → drop all items from a source.
        - path=<specific> → drop that exact item.
        """
        if path is None:
            count = len(self._active.get(agent_id, []))
            self._active[agent_id] = []
            return count

        target = path.strip().lower()
        if target in ("stale", "*stale*"):
            return self.forget_stale(agent_id)
        if target.startswith("source:"):
            return self.forget_source(agent_id, target.split(":", 1)[1])

        before = len(self._active.get(agent_id, []))
        self._active[agent_id] = [
            c for c in self._active.get(agent_id, [])
            if c.path != path
        ]
        return before - len(self._active[agent_id])

    def forget_source(self, agent_id: str, source: str) -> int:
        """Drop all items of a given source type (e.g., 'search', 'memory')."""
        before = len(self._active.get(agent_id, []))
        self._active[agent_id] = [
            c for c in self._active.get(agent_id, [])
            if c.source != source
        ]
        return before - len(self._active[agent_id])

    def forget_stale(self, agent_id: str, min_turns: int = STALE_TURNS) -> int:
        """Drop stale, unpinned items not referenced for min_turns."""
        turn = self._turns.get(agent_id, 0)
        before = len(self._active.get(agent_id, []))
        self._active[agent_id] = [
            c
            for c in self._active.get(agent_id, [])
            if c.pinned or (turn - c.last_referenced) < min_turns
        ]
        removed = before - len(self._active[agent_id])
        if removed:
            log.debug("Auto-forgot %d stale context item(s)", removed)
        return removed

    def smart_prune(
        self,
        agent_id: str,
        query: str = "",
        drop_stale_even_if_under_budget: bool = True,
    ) -> int:
        """Intelligently prune context to fit the token budget.

        Strategy (in order):
        1. Drop stale items (optionally even if budget is not exceeded).
        2. If still over budget, drop lowest-relevance unpinned items.
        3. Never drop pinned items.
        """
        items = self._active.get(agent_id, [])
        if not items:
            return 0

        _ = query  # reserved for future relevance-aware pruning
        total = sum(self._estimate_tokens(c.content) for c in items)
        removed = 0

        if drop_stale_even_if_under_budget:
            removed += self.forget_stale(agent_id)
            items = self._active.get(agent_id, [])
            total = sum(self._estimate_tokens(c.content) for c in items)

        if total <= self.max_tokens:
            return removed

        # Pass 2: drop lowest-relevance unpinned items
        if total > self.max_tokens:
            droppable = [c for c in items if not c.pinned]
            droppable.sort(key=lambda c: c.relevance)
            for item in droppable:
                if total <= self.max_tokens:
                    break
                total -= self._estimate_tokens(item.content)
                items.remove(item)
                removed += 1
                log.debug("Pruned low-relevance: %s (%.1f)",
                           item.path, item.relevance)

        return removed

    def prune(self, agent_id: str) -> int:
        """Legacy prune — calls smart_prune."""
        return self.smart_prune(agent_id)

    # ══════════════════════════════════════════════════════════════════════
    #  QUERYING
    # ══════════════════════════════════════════════════════════════════════

    def get_active(self, agent_id: str) -> list[ContextItem]:
        return self._active.get(agent_id, [])

    def active_token_count(self, agent_id: str) -> int:
        return sum(
            self._estimate_tokens(c.content)
            for c in self._active.get(agent_id, [])
        )

    def inventory(self, agent_id: str) -> list[dict]:
        """Return a concise manifest of what's in active context."""
        turn = self._turns.get(agent_id, 0)
        result = []
        for item in self._active.get(agent_id, []):
            result.append({
                "path": item.path,
                "source": item.source,
                "tokens": self._estimate_tokens(item.content),
                "relevance": round(item.relevance, 1),
                "stale": (turn - item.last_referenced) >= STALE_TURNS,
                "pinned": item.pinned,
                "age_turns": turn - item.turn_loaded,
            })
        return result

    # ══════════════════════════════════════════════════════════════════════
    #  SESSION PERSISTENCE
    # ══════════════════════════════════════════════════════════════════════

    def save_exchange(
        self,
        session_id: str,
        agent_id: str,
        user_msg: str,
        assistant_msg: str,
    ) -> None:
        """Persist a conversation turn to the session file."""
        self.sessions.append_message(session_id, "user", "user", user_msg)
        self.sessions.append_message(
            session_id, "assistant", agent_id, assistant_msg,
        )

    # ══════════════════════════════════════════════════════════════════════
    #  RENDERING FOR LLM
    # ══════════════════════════════════════════════════════════════════════

    def render_context_block(self, agent_id: str) -> str:
        """Render active context as a text block for the system prompt.

        Includes a manifest header so the agent can see what's loaded
        and decide what to [FORGET:path].
        """
        items = self._active.get(agent_id, [])
        if not items:
            return ""

        turn = self._turns.get(agent_id, 0)
        total_tokens = self.active_token_count(agent_id)

        parts = [
            "<active_context>",
            f"[{len(items)} items | ~{total_tokens} tokens "
            f"| budget {self.max_tokens}]",
        ]

        for item in items:
            age = turn - item.last_referenced
            flags = ""
            if item.pinned:
                flags += " pinned"
            if age >= STALE_TURNS:
                flags += " STALE"
            header = (
                f"[{item.source} | {item.path} | "
                f"rel={item.relevance:.1f} | age={age}t{flags}]"
            )
            parts.append(f"{header}\n{item.content}\n")

        parts.append("</active_context>")
        parts.append(
            "Use [LOAD:path] to load a vault note/session. "
            "Use [FORGET:path] to drop unneeded context. "
            "Use [FORGET:stale] for old items. "
            "Use [FORGET:all] to clear everything."
        )
        return "\n".join(parts)

    # ══════════════════════════════════════════════════════════════════════
    #  INTERNAL
    # ══════════════════════════════════════════════════════════════════════

    def _touch(self, agent_id: str, path: str, turn: int) -> None:
        """Bump last_referenced for an item already in context."""
        for item in self._active.get(agent_id, []):
            if item.path == path:
                item.last_referenced = turn
                return

    def _search_workspace(
        self,
        query: str,
        top_k: int,
        turn: int,
    ) -> list[ContextItem]:
        """Lightweight fallback search in current workspace (outside vault)."""
        q = query.strip().lower()
        if len(q) < 3:
            return []

        results: list[ContextItem] = []
        try:
            root = self.workspace_root
            if not root.exists():
                return []

            scanned = 0
            for path in root.rglob("*"):
                if len(results) >= top_k or scanned >= 400:
                    break
                scanned += 1

                if not path.is_file():
                    continue
                if any(skip in path.parts for skip in WORKSPACE_SKIP_DIRS):
                    continue
                if path.suffix.lower() not in WORKSPACE_SCAN_EXTS:
                    continue
                if path.stat().st_size > 120_000:
                    continue

                rel = str(path.relative_to(root))
                score = 0.0
                content = ""

                # filename match bonus
                if q in path.name.lower():
                    score += 5.0

                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                pos = text.lower().find(q)
                if pos >= 0:
                    score += 3.0
                    start = max(0, pos - 200)
                    end = min(len(text), pos + 400)
                    content = text[start:end]
                elif score > 0:
                    content = text[:500]

                if score <= 0:
                    continue

                results.append(ContextItem(
                    source="workspace",
                    content=content.strip(),
                    relevance=score,
                    path=f"workspace:{rel}",
                    turn_loaded=turn,
                    last_referenced=turn,
                ))
        except Exception:
            return []

        results.sort(key=lambda c: c.relevance, reverse=True)
        return results[:top_k]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4

    # Legacy alias
    def get_relevant(
        self, agent_id: str, query: str, top_k: int = 5,
    ) -> list[ContextItem]:
        """Alias for search_and_load (backward compat)."""
        return self.search_and_load(agent_id, query, top_k)
