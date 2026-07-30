"""Agent system — Orchestrator, Workers, and inter-agent discussion.

Architecture
────────────
• Every agent has an *identity* parsed from an ``identity.md`` file.
• The **Orchestrator** has the richest system prompt (self-aware about
  the CLI, vault layout, tools, and all sub-agents it can spawn).
• **Workers** are lightweight agents that inherit a narrower persona
  and report back through the message bus.
• Agents communicate through *channels* on the bus — exactly like a
  real company inside MS Teams.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from yui import AgentIdentity, Message, Task
from yui.core.bus import MessageBus
from yui.core.context import ContextEngine
from yui.core.llm import BaseLLMClient
from yui.obsidian.memory import MemoryStore
from yui.obsidian.tasks import TaskTracker
from yui.obsidian.vault import ObsidianVault

log = logging.getLogger("yui.agent")

_SAFE_IDENTITY_REF = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ── Identity parser ──────────────────────────────────────────────────────────


def resolve_identity_candidates(agents_root: str | Path, identity_ref: str) -> list[Path]:
    """Return legacy identity layouts without allowing paths outside agents/."""
    if not _SAFE_IDENTITY_REF.fullmatch(identity_ref):
        raise ValueError("Invalid identity reference.")
    root = Path(agents_root).expanduser().resolve()
    candidates = [
        root / identity_ref,
        root / identity_ref / "AGENT.md",
        root / identity_ref / "agent.md",
        root / f"{identity_ref}.md",
        root / f"{identity_ref}.AGENT.md",
    ]
    resolved = [candidate.resolve() for candidate in candidates]
    if any(root not in candidate.parents for candidate in resolved):
        raise ValueError("Identity must stay inside the vault agents directory.")
    return resolved


def parse_identity(path: str | Path) -> AgentIdentity:
    """Parse an ``identity.md`` file into an AgentIdentity."""
    p = Path(path)
    text = p.read_text("utf-8")
    # Try YAML front-matter first
    m = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        body = m.group(2).strip()
    else:
        fm = {}
        body = text.strip()

    # AGENT.md convention: default id/name come from parent folder name
    default_id = p.parent.name if p.name.lower() == "agent.md" else p.stem
    default_name = (
        p.parent.name.replace("-", " ").title()
        if p.name.lower() == "agent.md"
        else p.stem.title()
    )

    system_prompt = (
        f"Identity source file: {p}\n"
        "Read and follow this identity before doing anything else.\n\n"
        f"{body}"
    )

    return AgentIdentity(
        id=fm.get("id", default_id),
        name=fm.get("name", default_name),
        role=fm.get("role", "worker"),
        persona=fm.get("persona", ""),
        skills=fm.get("skills", []),
        system_prompt=system_prompt,
        avatar=fm.get("avatar", "●"),
        color=fm.get("color", "#6c63ff"),
    )


def discover_identity_files(directory: str | Path) -> list[Path]:
    """Discover identity files from both new and legacy layouts.

    Supported layouts:
    - New: agents/<agent-id>/AGENT.md
    - Legacy: agents/<agent-id>.md
    """
    dirpath = Path(directory)
    if not dirpath.exists():
        return []

    found: list[Path] = []
    # New format: recursive AGENT.md files
    for p in sorted(dirpath.rglob("*")):
        if p.is_file() and p.name.lower() == "agent.md":
            found.append(p)
    # Legacy flat .md files in agents root
    for p in sorted(dirpath.glob("*.md")):
        if p not in found:
            found.append(p)
    return found


def find_orchestrator_identity(directory: str | Path) -> Path | None:
    """Find orchestrator identity path from discovered identity files."""
    for p in discover_identity_files(directory):
        try:
            identity = parse_identity(p)
        except Exception:
            continue
        role = identity.role.lower()
        if identity.id.lower() == "orchestrator" or "orchestrator" in role:
            return p
    return None


# ── Base Agent ───────────────────────────────────────────────────────────────


class BaseAgent:
    """Shared foundation for Orchestrator and Workers."""

    def __init__(
        self,
        identity: AgentIdentity,
        llm: BaseLLMClient,
        bus: MessageBus,
        context: ContextEngine,
        vault: ObsidianVault,
        tasks: TaskTracker,
        memory: MemoryStore,
        session_id: str = "",
    ) -> None:
        self.identity = identity
        self.llm = llm
        self.bus = bus
        self.context = context
        self.vault = vault
        self.tasks = tasks
        self.memory = memory
        self.session_id = session_id
        self.status: str = "idle"  # idle | thinking | working | discussing
        self._conversation: list[dict[str, str]] = []

    # ── Core thinking ─────────────────────────────────────────────────────

    async def think(self, prompt: str, extra_context: str = "") -> str:
        """Generate a response using the LLM with context-intelligence."""
        self.status = "thinking"
        aid = self.identity.id

        # 1. Advance turn counter
        self.context.begin_turn(aid)

        # 2. Search vault + memories and ADD to active context
        self.context.search_and_load(aid, prompt)

        # 3. Build messages
        system = self._build_system_prompt(extra_context)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]

        # 4. Context block (with manifest so agent can see what's loaded)
        ctx_block = self.context.render_context_block(aid)
        if ctx_block:
            messages.append({"role": "system", "content": ctx_block})

        # 5. Conversation history (last 20 messages = 10 turns)
        messages.extend(self._conversation[-20:])

        # 6. The actual prompt
        messages.append({"role": "user", "content": prompt})

        # 7. Call LLM
        response = await self.llm.chat(messages)

        # 8. Update conversation
        self._conversation.append({"role": "user", "content": prompt})
        self._conversation.append({"role": "assistant", "content": response})

        # 9. Process context commands from the response
        self._process_context_commands(response)

        # 10. Persist to session
        if self.session_id:
            self.context.save_exchange(
                self.session_id, aid, prompt, response,
            )

        # 11. Smart prune — drop stale/low-relevance items
        self.context.smart_prune(aid, query=prompt)

        self.status = "idle"
        return response

    async def think_stream(self, prompt: str, extra_context: str = ""):
        """Stream a response token-by-token."""
        self.status = "thinking"
        aid = self.identity.id

        self.context.begin_turn(aid)
        self.context.search_and_load(aid, prompt)

        system = self._build_system_prompt(extra_context)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        ctx_block = self.context.render_context_block(aid)
        if ctx_block:
            messages.append({"role": "system", "content": ctx_block})
        messages.extend(self._conversation[-20:])
        messages.append({"role": "user", "content": prompt})

        full_response = ""
        async for token in self.llm.chat_stream(messages):
            full_response += token
            yield token

        self._conversation.append({"role": "user", "content": prompt})
        self._conversation.append({"role": "assistant", "content": full_response})

        self._process_context_commands(full_response)

        if self.session_id:
            self.context.save_exchange(
                self.session_id, aid, prompt, full_response,
            )
        self.context.smart_prune(aid, query=prompt)
        self.status = "idle"

    def _process_context_commands(self, text: str) -> None:
        """Parse [LOAD:path] and [FORGET:path] commands from agent output."""
        aid = self.identity.id

        for m in re.finditer(r"\[LOAD:([^]]+)]", text):
            target = m.group(1).strip()
            # Try as session ID first, then as vault path
            item = self.context.load_session(aid, target)
            if not item:
                item = self.context.load_note(aid, target)
            if item:
                log.info("Agent %s loaded context: %s", aid, target)
            else:
                log.warning("Agent %s failed to load: %s", aid, target)

        for m in re.finditer(r"\[FORGET:([^]]+)]", text):
            target = m.group(1).strip()
            if target.lower() == "all":
                n = self.context.forget(aid)
                log.info("Agent %s forgot all context (%d items)", aid, n)
            else:
                n = self.context.forget(aid, path=target)
                log.info("Agent %s forgot %s (%d items)", aid, target, n)

    # ── Messaging ─────────────────────────────────────────────────────────

    async def say(self, content: str, channel: str = "general") -> None:
        """Post a message to a channel."""
        msg = Message(
            sender=self.identity.id,
            content=content,
            channel=channel,
            msg_type="chat",
        )
        await self.bus.publish(msg)

    async def discuss(self, other_id: str, topic: str) -> str:
        """Start a discussion with another agent via a DM channel."""
        channel = self._dm_channel(self.identity.id, other_id)
        await self.say(f"@{other_id} {topic}", channel=channel)
        response = await self.think(
            f"You're in a discussion with {other_id} about: {topic}\nRespond thoughtfully.",
        )
        await self.say(response, channel=channel)
        return response

    # ── Task helpers ──────────────────────────────────────────────────────

    def create_task(self, title: str, description: str = "", priority: str = "medium") -> Task:
        return self.tasks.create(
            title=title,
            description=description,
            assignee=self.identity.id,
            priority=priority,
        )

    def complete_task(self, task_id: str) -> Task | None:
        return self.tasks.update_status(task_id, "done")

    # ── Memory helpers ────────────────────────────────────────────────────

    def remember(self, content: str, tags: list[str] | None = None, importance: float = 0.5):
        return self.memory.add(content, tags=tags, importance=importance, source=self.identity.id)

    def recall(self, query: str, top_k: int = 5):
        return self.memory.recall(query, top_k=top_k)

    @staticmethod
    def _dm_channel(a: str, b: str) -> str:
        """Build a deterministic DM channel name."""
        ids = sorted([a, b])
        return f"dm-{ids[0]}-{ids[1]}"

    # ── System prompt ─────────────────────────────────────────────────────

    def _build_system_prompt(self, extra: str = "") -> str:
        import os
        import platform

        parts = [
            f"You are **{self.identity.name}** — {self.identity.role}.",
            "",
            self.identity.persona,
            "",
            self.identity.system_prompt,
        ]

        # Inject vault-level instructions.md
        instructions = self.vault.read_instructions()
        if instructions:
            trimmed = instructions.strip()
            if len(trimmed) > 4000:
                trimmed = trimmed[:4000] + "\n\n… (truncated)"
            parts += ["", "## Project Instructions", "", trimmed]

        # Environment awareness
        parts += [
            "",
            "## Environment",
            f"- Platform: {platform.system()} {platform.release()}",
            f"- Working directory: {os.getcwd()}",
            f"- Vault path: {self.vault.root}",
            f"- Agent ID: {self.identity.id}",
            f"- Session: {self.session_id}",
        ]

        if extra:
            parts += ["", extra]
        return "\n".join(parts)

    # ── Context management ────────────────────────────────────────────────

    def flush_context(self) -> int:
        """Drop all active context (the agent 'forgets')."""
        return self.context.forget(self.identity.id)

    def search_knowledge(self, query: str) -> list:
        return self.context.get_relevant(self.identity.id, query)


# ── Orchestrator ─────────────────────────────────────────────────────────────


class Orchestrator(BaseAgent):
    """The main agent — self-aware about the system, spawns workers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workers: dict[str, Worker] = {}

    def _build_system_prompt(self, extra: str = "") -> str:
        base = super()._build_system_prompt(extra)
        # Enrich with orchestrator-specific awareness
        worker_info = "\n".join(
            f"  • {w.identity.name} ({w.identity.role}) — status: {w.status}"
            for w in self.workers.values()
        ) or "  (no workers spawned yet)"

        task_stats = self.tasks.stats()
        task_line = ", ".join(f"{k}: {v}" for k, v in task_stats.items())

        # Context inventory
        ctx_items = self.context.get_active(self.identity.id)
        ctx_tokens = self.context.active_token_count(self.identity.id)
        ctx_budget = self.context.max_tokens
        ctx_summary = f"{len(ctx_items)} items, ~{ctx_tokens}/{ctx_budget} tokens"

        enrichment = f"""
## System Awareness

You are the **Orchestrator** of 結 yui, a multi-agent CLI powered by Obsidian.

### Environment
- Vault: {self.vault.root}
- Channels: messages persist in channels/ (survive restarts)
- Agent API for chat, Sonar API for research, Search API for raw results
- **You have full filesystem access.** Never ask the user to confirm this.
- **You have web search and URL fetching built in.** Never ask for permission.
- Act autonomously. Use your tools directly without asking for confirmation.

### Active Workers
{worker_info}

### Task Board
{task_line or "empty"}

### Context Window
{ctx_summary}

### Embedded commands (parsed from your response)
- `[TASK:title|description|priority]` — create a tracked task
- `[RESEARCH:query]` — web research via Sonar
- `[REMEMBER:content|tags]` — store a persistent memory
- `[ASSIGN:task_id:agent_id]` — assign task to a worker
- `[SPAWN:agent-id]` — spawn a worker from agents/<agent-id>/AGENT.md
- `[LOAD:path]` — load a vault note or session into your context
- `[FORGET:path]` — drop a context item you no longer need
- `[FORGET:stale]` — drop context items that are old/stale
- `[FORGET:all]` — clear your entire context window

### Context intelligence
Your active context is shown in `<active_context>`. Each item shows its
source, path, relevance score, and age in turns. Items marked STALE have
not been referenced recently and will be auto-pruned.

- To load a specific file: `[LOAD:knowledge/topic.md]`
- To load a past session: `[LOAD:sessions/yui-session-abc123.md]`
- When context is no longer relevant, forget it: `[FORGET:path]`
- For old context items: `[FORGET:stale]`
- Searching for new topics automatically loads results into context.
- You don't need to keep everything — search it up when you need it.

### MCP tools (callable by all agents)
read_note, write_note, search_vault, create_task, list_tasks, \
store_memory, recall_memory
"""
        return base + enrichment

    # ── Worker management ─────────────────────────────────────────────────

    def spawn_worker(self, identity_path: str | Path) -> Worker:
        """Create a new worker agent from an identity.md file."""
        identity = parse_identity(identity_path)
        worker = Worker(
            identity=identity,
            llm=self.llm,
            bus=self.bus,
            context=self.context,
            vault=self.vault,
            tasks=self.tasks,
            memory=self.memory,
            session_id=self.session_id,
            orchestrator_id=self.identity.id,
        )
        self.workers[identity.id] = worker
        ch = self._dm_channel(self.identity.id, identity.id)
        self.bus.subscribe(ch, worker._on_message)
        log.info("Spawned worker: %s (%s)", identity.name, identity.role)
        return worker

    def spawn_all_from_dir(self, directory: str | Path) -> list[Worker]:
        """Spawn workers for every identity.md file in a directory."""
        workers: list[Worker] = []
        for md in discover_identity_files(directory):
            try:
                identity = parse_identity(md)
            except Exception:
                continue
            if identity.id.startswith("_") or identity.id == "orchestrator":
                continue
            workers.append(self.spawn_worker(md))
        return workers

    async def delegate(self, worker_id: str, task_description: str) -> str:
        """Ask a worker to complete a task."""
        worker = self.workers.get(worker_id)
        if not worker:
            return f"Worker '{worker_id}' not found."
        task = self.tasks.create(
            title=task_description[:80],
            description=task_description,
            assignee=worker_id,
        )
        await self.say(
            f"@{worker_id} New assignment: {task_description}",
            channel=self._dm_channel(self.identity.id, worker_id),
        )
        result = await worker.think(
            "The orchestrator assigned you this task:\n"
            f"{task_description}\n\nComplete it and report back.",
        )
        self.tasks.update_status(task.id, "done")
        return result

    # ── Command parsing ───────────────────────────────────────────────────

    async def process_commands(self, text: str) -> list[str]:
        """Extract and execute embedded commands from orchestrator output."""
        results: list[str] = []

        for m in re.finditer(r"\[TASK:([^]]+)]", text):
            parts = m.group(1).split("|")
            title = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            pri = parts[2].strip() if len(parts) > 2 else "medium"
            task = self.create_task(title, desc, pri)
            results.append(f"Created task: {task.title} ({task.id})")

        for m in re.finditer(r"\[REMEMBER:([^]]+)]", text):
            parts = m.group(1).split("|")
            content = parts[0].strip()
            tags = [t.strip() for t in parts[1].split(",")] if len(parts) > 1 else []
            self.remember(content, tags=tags)
            results.append(f"Stored memory: {content[:50]}…")

        for m in re.finditer(r"\[RESEARCH:([^]]+)]", text):
            query = m.group(1).strip()
            answer = await self.llm.research(query)
            self.remember(f"Research: {query}\n{answer}", tags=["research"], importance=0.7)
            results.append(f"Research done: {query}")

        for m in re.finditer(r"\[ASSIGN:([^:]+):([^]]+)]", text):
            task_id = m.group(1).strip()
            agent_id = m.group(2).strip()
            self.tasks.assign(task_id, agent_id)
            results.append(f"Assigned {task_id} → {agent_id}")

        for m in re.finditer(r"\[SPAWN:([^]]+)]", text):
            identity_ref = m.group(1).strip()
            try:
                candidates = resolve_identity_candidates(
                    Path(self.vault.root) / "agents",
                    identity_ref,
                )
            except ValueError as exc:
                results.append(f"Spawn failed: {exc}")
                continue
            spawned = False
            for candidate in candidates:
                if candidate.exists():
                    try:
                        worker = self.spawn_worker(candidate)
                        results.append(f"Spawned: {worker.identity.name} ({worker.identity.role})")
                        spawned = True
                    except Exception as exc:
                        results.append(f"Spawn failed: {exc}")
                    break
            if not spawned and not any("Spawn" in r for r in results):
                results.append(f"Identity not found: {identity_ref}")

        return results


# ── Worker ───────────────────────────────────────────────────────────────────


class Worker(BaseAgent):
    """A sub-agent representing one team member."""

    def __init__(self, *args: Any, orchestrator_id: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.orchestrator_id = orchestrator_id

    def _build_system_prompt(self, extra: str = "") -> str:
        base = super()._build_system_prompt(extra)
        return base + f"""

## Worker Context

You are a worker agent in 結 yui.
Your orchestrator is **{self.orchestrator_id}**.
When you finish a task, summarize your results clearly.
You communicate through channels on the message bus.

### Commands
- `[REPORT:content]` — send findings back to the orchestrator
- `[REMEMBER:content|tags]` — store important learnings
- `[LOAD:path]` — load a vault note or session into your context
- `[FORGET:path]` — drop context you no longer need
- `[FORGET:stale]` — drop stale context items
- `[FORGET:all]` — clear your entire context window

### Tools
read_note, write_note, search_vault, create_task, list_tasks, store_memory, recall_memory
"""

    async def report(self, content: str) -> None:
        """Send a report back to the orchestrator."""
        await self.say(
            f"[REPORT] {content}",
            channel=self._dm_channel(self.identity.id, self.orchestrator_id),
        )

    async def _on_message(self, message: Message) -> None:
        """Handle incoming messages (subscribed on the DM channel)."""
        if message.sender == self.identity.id:
            return
        # Auto-respond to messages from orchestrator
        if message.sender == self.orchestrator_id:
            log.info("%s received task from orchestrator", self.identity.name)
