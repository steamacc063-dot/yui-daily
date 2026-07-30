"""Minimal skill system — agents load skills to gain capabilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("yui.skills")


@dataclass
class Skill:
    """A capability module that enriches an agent's system prompt and tools."""
    name: str
    description: str
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)  # names in the MCP registry
    tags: list[str] = field(default_factory=list)


class SkillRegistry:
    """Discovers and manages skills available to agents."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        log.debug("Registered skill: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def prompt_for(self, skill_names: list[str]) -> str:
        """Build a combined system-prompt addendum from multiple skills."""
        parts: list[str] = []
        for name in skill_names:
            skill = self._skills.get(name)
            if skill and skill.system_prompt:
                parts.append(f"## Skill: {skill.name}\n{skill.system_prompt}")
        return "\n\n".join(parts)


def load_builtin_skills() -> SkillRegistry:
    """Create a registry pre-loaded with the default skills."""
    registry = SkillRegistry()

    registry.register(Skill(
        name="research",
        description="Web research using Perplexity Sonar",
        system_prompt=(
            "You have access to web research. When asked to research something, "
            "use the research capability to find accurate, up-to-date information. "
            "Always cite sources and distinguish facts from speculation."
        ),
        tools=["search_vault", "recall_memory", "store_memory"],
        tags=["research", "web"],
    ))

    registry.register(Skill(
        name="writer",
        description="Content creation and document writing",
        system_prompt=(
            "You are a skilled writer. Write clearly, concisely, and with purpose. "
            "Match the tone to the audience. Structure long pieces with headers. "
            "Prefer active voice. Cut filler words ruthlessly."
        ),
        tools=["write_note", "read_note"],
        tags=["writing", "content"],
    ))

    registry.register(Skill(
        name="planner",
        description="Task breakdown and project planning",
        system_prompt=(
            "You break down complex objectives into concrete, actionable tasks. "
            "Each task should be completable in one work session. "
            "Assign priorities realistically. Identify dependencies."
        ),
        tools=["create_task", "list_tasks"],
        tags=["planning", "tasks"],
    ))

    registry.register(Skill(
        name="analyst",
        description="Data analysis and insight extraction",
        system_prompt=(
            "You analyse information methodically. Look for patterns, anomalies, "
            "and causal relationships. Present findings with evidence. "
            "Quantify when possible. Acknowledge uncertainty."
        ),
        tools=["search_vault", "recall_memory"],
        tags=["analysis", "data"],
    ))

    return registry
