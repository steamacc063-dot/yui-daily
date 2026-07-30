"""Async message bus — the nervous system connecting all agents."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

from yui import Message

Subscriber = Callable[[Message], Coroutine[Any, Any, None]]


class MessageBus:
    """Pub/sub bus for inter-agent communication.

    Channels are logical groupings (``general``, ``tasks``, ``research``).
    Agents subscribe to channels; messages flow to all subscribers.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._history: dict[str, list[Message]] = defaultdict(list)
        self._global: list[Subscriber] = []            # hear everything
        self._lock = asyncio.Lock()

    # ── Pub ───────────────────────────────────────────────────────────────

    async def publish(self, message: Message) -> None:
        """Send a message to its channel and all global listeners."""
        async with self._lock:
            self._history[message.channel].append(message)

        tasks: list[Coroutine] = []
        for sub in self._subscribers.get(message.channel, []):
            tasks.append(sub(message))
        for sub in self._global:
            tasks.append(sub(message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── Sub ───────────────────────────────────────────────────────────────

    def subscribe(self, channel: str, callback: Subscriber) -> None:
        self._subscribers[channel].append(callback)

    def subscribe_all(self, callback: Subscriber) -> None:
        """Subscribe to every channel (useful for the orchestrator)."""
        self._global.append(callback)

    def unsubscribe(self, channel: str, callback: Subscriber) -> None:
        subs = self._subscribers.get(channel, [])
        if callback in subs:
            subs.remove(callback)

    # ── History ───────────────────────────────────────────────────────────

    def history(self, channel: str, limit: int = 50) -> list[Message]:
        return self._history.get(channel, [])[-limit:]

    def all_history(self, limit: int = 100) -> list[Message]:
        all_msgs: list[Message] = []
        for msgs in self._history.values():
            all_msgs.extend(msgs)
        all_msgs.sort(key=lambda m: m.timestamp)
        return all_msgs[-limit:]

    @property
    def channels(self) -> list[str]:
        return sorted(set(self._history.keys()) | set(self._subscribers.keys()))
