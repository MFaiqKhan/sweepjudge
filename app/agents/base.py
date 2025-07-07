"""Base class shared by all micro-agents.

Agents run as standalone asyncio tasks. Each has a unique `agent_id` and
receives `Task` objects from the orchestrator via an injected `inbox`
`asyncio.Queue`. When done, it can push follow-up tasks to the orchestrator
through `emit_task` callback and send karma deltas through
`emit_karma`.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from app.core import Task

logger = logging.getLogger(__name__)


EmitTaskFn = Callable[[Task], Awaitable[None]]
EmitKarmaFn = Callable[[str, int, str | None], Awaitable[None]]


class BaseAgent(ABC):
    def __init__(
        self,
        agent_id: str,
        inbox: asyncio.Queue[Task],
        *,
        emit_task: EmitTaskFn,
        emit_karma: EmitKarmaFn,
    ) -> None:
        self.agent_id = agent_id
        self._inbox = inbox
        self._emit_task = emit_task
        self._emit_karma = emit_karma

    # ---------------------------------------------------------------------
    # Life-cycle
    # ---------------------------------------------------------------------

    async def run_forever(self) -> None:
        while True:
            task = await self._inbox.get()
            try:
                await self._handle(task)
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("%s failed to handle task %s: %s", self.agent_id, task.id, exc)
                await self._emit_karma(self.agent_id, -1, reason="exception")

    # ------------------------------------------------------------------
    # To be implemented by subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    async def _handle(self, task: Task) -> None:  # pragma: no cover
        """Process a task. Subclass must implement."""
        raise NotImplementedError 