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
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, ClassVar, List, Optional
from uuid import UUID

from app.core import Task, TaskStatus
from app.core.agent_directory import AgentDirectory
from app.core.task_queue import TaskQueue

logger = logging.getLogger(__name__)


EmitTaskFn = Callable[[Task], Awaitable[None]]
EmitKarmaFn = Callable[[str, int, str | None], Awaitable[None]]
MarkCompletedFn = Callable[[UUID, str], Awaitable[None]]
MarkFailedFn = Callable[[UUID, str], Awaitable[None]]


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
        mark_completed: MarkCompletedFn,
        mark_failed: MarkFailedFn,
        agent_directory: Optional[AgentDirectory] = None,
        task_queue: Optional[TaskQueue] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        self.agent_id = agent_id
        self._inbox = inbox
        self._emit_task = emit_task
        self._emit_karma = emit_karma
        self._mark_completed = mark_completed
        self._mark_failed = mark_failed
        self._agent_directory = agent_directory
        self._task_queue = task_queue
        self.config = config or {}
        
    async def stop(self) -> None:
        """Gracefully unregister the agent from the directory."""
        if self._agent_directory:
            logger.info(f"Unregistering agent {self.agent_id}")
            await self._agent_directory.unregister(self.agent_id)

    # ---------------------------------------------------------------------
    # Life-cycle
    # ---------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Main agent loop: register with directory, then process tasks."""
        try:
            if self._agent_directory:
                task_types = self.TASK_TYPES or await self._auto_detect_task_types()
                if not task_types:
                    logger.warning(f"{self.agent_id} has no task types, won't register")
                else:
                    logger.info(f"{self.agent_id} registering with task_types {task_types}")
                    await self._agent_directory.register(self.agent_id, task_types)
            
            while True:
                task = await self._inbox.get()
                
                # If this agent is a reviewer, it follows a different logic and doesn't get reviewed.
                if self.TASK_TYPES and "Review_Artifact" in self.TASK_TYPES:
                    await self._handle(task)
                    if task.status == TaskStatus.completed:
                         await self._mark_completed(task.id, self.agent_id)
                    continue

                start_time = time.time()
                try:
                    await self._handle(task)
                    duration = time.time() - start_time

                    if task.status == TaskStatus.completed:
                        # Task is not 'completed' yet, it's 'pending_review'
                        task.status = TaskStatus.pending_review
                        await self._update_task_status_in_db(task.id, TaskStatus.pending_review, self.agent_id)

                        # Extract the artifact for the review payload
                        artifact_payload = None
                        if task.artifacts:
                            # We'll send the first artifact for review
                            artifact_payload = task.artifacts[0].model_dump(mode="json")

                        # Create a follow-up review task
                        review_task = Task(
                            task_type="Review_Artifact",
                            payload={
                                "original_task_id": task.id,
                                "original_agent_id": self.agent_id,
                                "artifact": artifact_payload,
                                "duration": duration,
                            },
                        )
                        await self._emit_task(review_task)
                        logger.info(f"Task {task.id} completed by {self.agent_id}. Submitted for review.")

                except Exception as exc:
                    logger.exception(f"{self.agent_id} failed to handle task {task.id}: {exc}")
                    await self._emit_karma(self.agent_id, -2, reason="unhandled_exception") # Harsher penalty
                    await self._mark_failed(task.id, self.agent_id)
        except asyncio.CancelledError:
            logger.info(f"Agent {self.agent_id} run_forever task cancelled.")
        finally:
            await self.stop()

    # Add a helper to update status without marking final
    async def _update_task_status_in_db(self, task_id: UUID, status: TaskStatus, agent_id: str):
        if self._task_queue:
            from app.core.models import DBTaskStatus
            db_status = DBTaskStatus(status.value)
            await self._task_queue._update_task_status(task_id, db_status, agent_id)

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