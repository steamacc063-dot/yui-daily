"""Local file/directory research — read local content, analyze via LLM.

Scans files, chunks them, and sends to the Perplexity API for analysis.
Supports text, code, markdown, config files, and more.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("yui.local_research")

# File extensions we can read
_TEXT_EXTENSIONS: set[str] = {
    ".md", ".txt", ".rst", ".org",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
    ".html", ".css", ".scss", ".less",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".sh", ".bash", ".zsh", ".fish",
    ".sql", ".graphql",
    ".xml", ".csv", ".log",
    ".dockerfile", ".makefile", ".gitignore",
    "",  # extensionless files like Makefile, Dockerfile
}

_SKIP_DIRS: set[str] = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".next", ".nuxt", "dist", "build", ".cache", ".ruff_cache",
    ".pytest_cache", "target", ".idea", ".vscode",
}

MAX_FILE_SIZE = 100_000      # 100KB per file
MAX_TOTAL_CHARS = 400_000    # ~100k tokens total budget
CHUNK_SIZE = 12_000          # ~3k tokens per chunk


def _is_readable(path: Path) -> bool:
    """Check if a file is a text file we should read."""
    if path.name.startswith("."):
        return False
    suffix = path.suffix.lower()
    name = path.name.lower()
    # Known extensionless files
    if suffix == "" and name in ("makefile", "dockerfile", "readme", "license", "changelog"):
        return True
    return suffix in _TEXT_EXTENSIONS


def scan_path(target: str | Path) -> list[dict[str, str]]:
    """Scan a file or directory and return readable file contents.

    Returns a list of ``{"path": str, "content": str}`` dicts.
    """
    target = Path(target).expanduser().resolve()
    files: list[dict[str, str]] = []
    total = 0

    if target.is_file():
        content = _read_file(target)
        if content:
            files.append({"path": str(target), "content": content})
        return files

    if not target.is_dir():
        return files

    for item in sorted(target.rglob("*")):
        if total >= MAX_TOTAL_CHARS:
            break
        if item.is_dir():
            continue
        if any(skip in item.parts for skip in _SKIP_DIRS):
            continue
        if not _is_readable(item):
            continue
        content = _read_file(item)
        if not content:
            continue
        files.append({
            "path": str(item.relative_to(target)),
            "content": content,
        })
        total += len(content)

    return files


def _read_file(path: Path) -> str:
    """Read a single file, respecting size limits."""
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def build_context(files: list[dict[str, str]], query: str = "") -> list[str]:
    """Chunk file contents into LLM-sized context blocks.

    Each chunk includes the file path header and content.
    Returns a list of prompt strings ready to send to the LLM.
    """
    if not files:
        return []

    # Build a single document with file headers
    parts: list[str] = []
    for f in files:
        header = f"── {f['path']} ──"
        parts.append(f"{header}\n{f['content']}\n")

    full_text = "\n".join(parts)

    # Chunk if needed
    chunks: list[str] = []
    while full_text:
        chunk = full_text[:CHUNK_SIZE]
        full_text = full_text[CHUNK_SIZE:]
        chunks.append(chunk)

    return chunks


async def research_local(
    llm,
    target: str,
    query: str = "",
) -> str:
    """Scan local files and analyze them with the LLM.

    Args:
        llm: Active LLM client instance.
        target: File path or directory path.
        query: Optional analysis question. Defaults to a general summary.

    Returns:
        The LLM's analysis as a string.
    """
    path = Path(target).expanduser().resolve()

    if not path.exists():
        return f"path not found: {path}"

    files = scan_path(path)
    if not files:
        return f"no readable files in {path}"

    chunks = build_context(files, query)
    file_count = len(files)
    label = path.name or str(path)

    if not query:
        query = (
            "Analyze these files. Provide a clear summary of the project structure, "
            "key components, patterns, and anything notable."
        )

    system = (
        "You are analyzing local files from the user's computer. "
        "Be precise and structured. Reference specific files by name."
    )

    if len(chunks) == 1:
        # Single chunk — straightforward
        prompt = f"{query}\n\nFiles ({file_count} from {label}):\n\n{chunks[0]}"
        return await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

    # Multi-chunk — summarize each, then compile
    summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        prompt = (
            f"Summarize this section ({i+1}/{len(chunks)}) from {label}.\n"
            f"Focus on: {query}\n\n{chunk}"
        )
        summary = await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        summaries.append(summary)

    # Final synthesis
    combined = "\n\n---\n\n".join(summaries)
    final_prompt = (
        f"Based on these summaries of {file_count} files from {label}, "
        f"provide a final comprehensive answer to: {query}\n\n{combined}"
    )
    return await llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": final_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
