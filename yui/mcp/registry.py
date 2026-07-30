"""MCP (Model Context Protocol) tool registry.

Agents can call tools through this registry.  Tools can be:
  • Built-in  (Obsidian ops, search, task management)
  • External  (loaded from MCP server configs)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

log = logging.getLogger("yui.mcp")


@dataclass
class MCPTool:
    """A single callable tool."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Coroutine[Any, Any, Any]] | None = None
    source: str = "builtin"  # builtin | external


class MCPRegistry:
    """Central registry for all MCP tools available to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, MCPTool] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s (%s)", tool.name, tool.source)

    def register_function(
        self,
        name: str,
        description: str,
        handler: Callable[..., Coroutine[Any, Any, Any]],
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.register(MCPTool(
            name=name,
            description=description,
            parameters=parameters or {},
            handler=handler,
        ))

    # ── Execution ─────────────────────────────────────────────────────────

    async def execute(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        if not tool.handler:
            raise ValueError(f"Tool '{name}' has no handler (external stub only)")
        return await tool.handler(**(arguments or {}))

    # ── Discovery ─────────────────────────────────────────────────────────

    def list_tools(self) -> list[MCPTool]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> MCPTool | None:
        return self._tools.get(name)

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-style function schemas for all tools."""
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters or {"type": "object", "properties": {}},
                },
            })
        return schemas

    # ── Loader ────────────────────────────────────────────────────────────

    def load_from_config(self, configs: list[dict[str, Any]]) -> int:
        """Load external tool stubs from MCP server configurations.

        Each config dict should have:
          - name: str
          - description: str
          - parameters: dict (JSON Schema)
          - source: str (server name)
        """
        loaded = 0
        for cfg in configs:
            self.register(MCPTool(
                name=cfg["name"],
                description=cfg.get("description", ""),
                parameters=cfg.get("parameters", {}),
                source=cfg.get("source", "external"),
            ))
            loaded += 1
        return loaded


def create_builtin_tools(
    vault,
    tasks,
    memory,
    search,
) -> MCPRegistry:
    """Wire up the default built-in tools."""
    registry = MCPRegistry()

    # ── Vault tools ───────────────────────────────────────────────────
    async def read_note(path: str) -> str:
        fm, body = vault.read_note(path)
        return body

    async def write_note(path: str, content: str) -> str:
        vault.write_note(path, content)
        return f"Written: {path}"

    async def search_vault(query: str, folder: str = "") -> str:
        results = search.search(query, folder=folder)
        return "\n".join(f"[{r.title}] {r.snippet}" for r in results)

    # ── Task tools ────────────────────────────────────────────────────
    async def create_task(title: str, description: str = "", priority: str = "medium") -> str:
        task = tasks.create(title=title, description=description, priority=priority)
        return f"Created task {task.id}: {task.title}"

    async def list_tasks(status: str = "") -> str:
        all_tasks = tasks.list_all(status=status or None)
        return "\n".join(f"[{t.status}] {t.title} ({t.id})" for t in all_tasks)

    # ── Memory tools ──────────────────────────────────────────────────
    async def store_memory(content: str, tags: str = "") -> str:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        mem = memory.add(content, tags=tag_list)
        return f"Stored memory {mem.id}"

    async def recall_memory(query: str) -> str:
        results = memory.recall(query)
        return "\n".join(f"[{m.id}] {m.content[:100]}" for m in results)

    # Register all
    for name, desc, handler in [
        ("read_note", "Read a note from the Obsidian vault", read_note),
        ("write_note", "Write content to an Obsidian note", write_note),
        ("search_vault", "Search the Obsidian vault", search_vault),
        ("create_task", "Create a new task on the board", create_task),
        ("list_tasks", "List tasks, optionally filtered by status", list_tasks),
        ("store_memory", "Store a memory for future recall", store_memory),
        ("recall_memory", "Search memories by query", recall_memory),
    ]:
        registry.register_function(name, desc, handler)

    return registry
