"""Full-text search across the Obsidian vault."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VaultSearchResult:
    path: str
    score: float
    snippet: str
    title: str = ""


class ObsidianSearch:
    """Simple but effective token-overlap search over the vault."""

    def __init__(self, vault_root: Path) -> None:
        self.root = vault_root

    # ── Public API ────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        folder: str = "",
        max_results: int = 10,
    ) -> list[VaultSearchResult]:
        """Return the best-matching notes for *query*."""
        base = self.root / folder if folder else self.root
        if not base.exists():
            return []

        query_lower = query.lower()
        terms = [t for t in query_lower.split() if len(t) > 1]
        hits: list[VaultSearchResult] = []

        for path in base.rglob("*.md"):
            if path.name.startswith("."):
                continue
            try:
                text = path.read_text("utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue

            score = self._score(text, query_lower, terms, path.stem)
            if score > 0:
                hits.append(
                    VaultSearchResult(
                        path=str(path.relative_to(self.root)),
                        score=score,
                        snippet=self._snippet(text, terms),
                        title=path.stem,
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:max_results]

    def search_by_tags(
        self,
        tags: list[str],
        folder: str = "",
        max_results: int = 10,
    ) -> list[VaultSearchResult]:
        """Find notes containing Obsidian-style ``#tag`` markers."""
        base = self.root / folder if folder else self.root
        if not base.exists():
            return []

        target = {t.lower().lstrip("#") for t in tags}
        hits: list[VaultSearchResult] = []

        for path in base.rglob("*.md"):
            try:
                text = path.read_text("utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue
            found = {m.lower() for m in re.findall(r"#([\w/-]+)", text)}
            overlap = target & found
            if overlap:
                hits.append(
                    VaultSearchResult(
                        path=str(path.relative_to(self.root)),
                        score=len(overlap) * 5.0,
                        snippet=text[:200],
                        title=path.stem,
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:max_results]

    # ── Scoring ───────────────────────────────────────────────────────────

    @staticmethod
    def _score(
        text: str,
        query_lower: str,
        terms: list[str],
        title: str,
    ) -> float:
        text_l = text.lower()
        score = 0.0
        # exact phrase
        if query_lower in text_l:
            score += 10.0
        # individual terms
        for term in terms:
            cnt = text_l.count(term)
            if cnt:
                score += min(cnt, 5) * 2.0
        # title match bonus
        title_l = title.lower()
        if query_lower in title_l:
            score += 20.0
        else:
            for term in terms:
                if term in title_l:
                    score += 5.0
        return score

    @staticmethod
    def _snippet(text: str, terms: list[str], ctx: int = 160) -> str:
        text_l = text.lower()
        best_pos = 0
        for term in terms:
            pos = text_l.find(term)
            if pos >= 0:
                best_pos = pos
                break
        start = max(0, best_pos - ctx // 2)
        end = min(len(text), best_pos + ctx)
        snip = text[start:end].replace("\n", " ").strip()
        if start > 0:
            snip = "…" + snip
        if end < len(text):
            snip += "…"
        return snip
