"""Async task queue + karma-aware scheduler.

Responsibilities:
1. Push tasks into a PostgreSQL tasks table with notification
2. Pop tasks and dispatch them to selected agents.
3. Use KarmaLedger to pick the best available agent for the task type.
4. (v2) Use AgentDirectory to find agents that can handle each task type.

The v2 architecture replaces the static agent registry with a dynamic
directory where agents register their capabilities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from app.core import Task
from app.core.agent_directory import AgentDirectory
from app.core.karma import KarmaLedger
from app.core.task_queue import TaskQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/karma")

# Map task_type -> list[agent_id] for v1 backward compatibility
# This is used only if no agent is registered for a task type
STATIC_AGENT_REGISTRY: dict[str, list[str]] = {
    "Fetch_Paper": ["fetcher-1", "fetcher-2", "fetcher-3"],
    "Summarise_Paper": ["reader-1", "reader-2", "reader-3"],
    "Extract_Metrics": ["metrician-1", "metrician-2"],
    "Compare_Methods": ["analyst-1", "analyst-2"],
    "Critique_Claim": ["debater"],
    "Synthesise_Report": ["synthesiser"],
}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class Scheduler:
    """Selects the best agent for each task based on karma scores and capabilities."""

    def __init__(
        self,
        karma: KarmaLedger,
        queue: TaskQueue,
        agent_directory: AgentDirectory,
        send_fn: Callable[[str, Task], asyncio.Future],
    ) -> None:
        """send_fn(agent_id, task) -> coroutine that actually delivers task."""

        self._karma = karma
        self._queue = queue
        self._agent_directory = agent_directory
        self._send_fn = send_fn
        self._use_fallback_registry = os.getenv("USE_FALLBACK_REGISTRY", "false").lower() == "true"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Main loop: pop tasks & dispatch."""
        
        # Initialize queue to start listening for notifications
        await self._queue.initialize()

        while True:
            task = await self._queue.pop(timeout=5)
            if task is None:
                continue  # idle
            
            agent_id = await self._select_agent(task.task_type)
            if agent_id is None:
                # No agent registered; requeue & sleep
                logger.warning("No agent available for task_type %s, requeuing", task.task_type)
                await self._queue.push(task)
                await asyncio.sleep(1)
                continue
                
            logger.info("Assigning task %s (%s) to agent %s", 
                      task.id, task.task_type, agent_id)
            await self._send_fn(agent_id, task)
            
            # Mark task as assigned to this agent
            # The agent will later mark it completed or failed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _select_agent(self, task_type: str) -> str | None:
        """Find the best agent for a task type based on karma scores."""
        # First try to get candidates from agent directory
        candidates = await self._agent_directory.get_candidates(task_type)
        
        # Fallback to static registry if enabled and no registered agents found
        if not candidates and self._use_fallback_registry:
            logger.info("No registered agents for %s, falling back to static registry", task_type)
            candidates = STATIC_AGENT_REGISTRY.get(task_type, [])
        
        if not candidates:
            return None
            
        # Fetch karma scores in parallel
        scores = await asyncio.gather(*[self._karma.score(a) for a in candidates])
        scored = list(zip(candidates, scores))
        
        # Sort descending by karma; break ties by agent_id for determinism
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[0][0]


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


async def create_scheduler(
    send_fn: Callable[[str, Task], asyncio.Future],
    *,
    karma: KarmaLedger | None = None,
) -> Scheduler:
    """Create a scheduler with all dependencies initialized."""
    karma = karma or KarmaLedger.from_env()
    
    # Create and initialize the task queue
    task_queue = TaskQueue.from_env()
    await task_queue.create_schema()
    
    # Create and initialize the agent directory
    agent_directory = AgentDirectory.from_env()
    await agent_directory.create_schema()
    
    # Create scheduler with all dependencies
    return Scheduler(karma, task_queue, agent_directory, send_fn) 