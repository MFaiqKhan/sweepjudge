"""Base class shared by all micro-agents.

Agents run as standalone asyncio tasks. Each has a unique `agent_id` and
receives `Task` objects from the orchestrator via an injected `inbox`
`asyncio.Queue`. When done, it can push follow-up tasks to the orchestrator
through `emit_task` callback and send karma deltas through
`emit_karma`.

In v2, agents also register themselves with the AgentDirectory.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, ClassVar, List, Optional

from app.core import Task
from app.core.agent_directory import AgentDirectory

logger = logging.getLogger(__name__)


EmitTaskFn = Callable[[Task], Awaitable[None]]
EmitKarmaFn = Callable[[str, int, str | None], Awaitable[None]]


class BaseAgent(ABC):
    # Subclasses should override this to declare which task types they can handle
    TASK_TYPES: ClassVar[List[str]] = []
    
    def __init__(
        self,
        agent_id: str,
        inbox: asyncio.Queue[Task],
        *,
        emit_task: EmitTaskFn,
        emit_karma: EmitKarmaFn,
        agent_directory: Optional[AgentDirectory] = None,
    ) -> None:
        self.agent_id = agent_id
        self._inbox = inbox
        self._emit_task = emit_task
        self._emit_karma = emit_karma
        self._agent_directory = agent_directory
        
    # ---------------------------------------------------------------------
    # Life-cycle
    # ---------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Main agent loop: register with directory, then process tasks."""
        # Register with the agent directory if available (v2)
        if self._agent_directory:
            # Get task types from class attribute or auto-detect from handler method
            task_types = self.TASK_TYPES or await self._auto_detect_task_types()
            if not task_types:
                logger.warning("%s has no task types, won't register", self.agent_id)
            else:
                logger.info("%s registering with task_types %s", self.agent_id, task_types)
                await self._agent_directory.register(self.agent_id, task_types)
        
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
        
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    
    async def _auto_detect_task_types(self) -> List[str]:
        """Auto-detect task types by examining the _handle method's code.
        
        This looks for patterns like `if task.task_type != "X":` in the
        handler method to infer what task types this agent supports.
        """
        try:
            # Get the source code of the _handle method
            source = inspect.getsource(self.__class__._handle)
            
            # Simple pattern matching for task types
            import re
            # Look for task.task_type == "X" or task.task_type != "X" patterns
            matches = re.findall(r'task\.task_type\s*(?:==|!=)\s*["\']([^"\']+)["\']', source)
            
            # If we found any task types, return them
            if matches:
                # If comparison is !=, the agent handles everything EXCEPT those types
                # For simplicity, we'll just return the matches
                return matches
                
            # Otherwise, assume it can handle any task type
            return []
            
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to auto-detect task types for %s: %s", self.agent_id, exc)
            return [] 