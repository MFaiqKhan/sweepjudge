"""Async task queue + karma-aware scheduler.

Responsibilities:
1. Push tasks (JSON blobs) onto a Redis list.
2. Pop tasks and dispatch them to selected agents.
3. Use KarmaLedger to pick the best available agent for the task type.

The MVP keeps agent discovery static via a config dict.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from typing import Any, Callable, Dict, List

import redis.asyncio as aioredis  # type: ignore
from redis.asyncio.client import Redis

from app.core import Task
from app.core.karma import KarmaLedger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = os.getenv("TASK_QUEUE_KEY", "task_queue")

# Map task_type -> list[agent_id]
STATIC_AGENT_REGISTRY: dict[str, list[str]] = {
    "Fetch_Paper": ["fetcher-1", "fetcher-2", "fetcher-3"],
    "Summarise_Paper": ["reader-1", "reader-2", "reader-3"],
    "Extract_Metrics": ["metrician-1", "metrician-2"],
    "Compare_Methods": ["analyst-1", "analyst-2"],
    "Critique_Claim": ["debater"],
    "Synthesise_Report": ["synthesiser"],
}

# ---------------------------------------------------------------------------
# Queue wrapper
# ---------------------------------------------------------------------------


class TaskQueue:
    def __init__(self, redis: Redis):
        self._redis = redis

    async def push(self, task: Task) -> None:
        await self._redis.rpush(QUEUE_KEY, task.model_dump_json())

    async def pop(self, timeout: int = 1) -> Task | None:
        # BLPOP returns (key, value) or None
        result = await self._redis.blpop(QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        return Task.model_validate_json(result[1])

    async def size(self) -> int:
        return await self._redis.llen(QUEUE_KEY)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class Scheduler:
    """Selects the best agent for each task based on karma scores."""

    def __init__(
        self,
        karma: KarmaLedger,
        queue: TaskQueue,
        send_fn: Callable[[str, Task], asyncio.Future],
    ) -> None:
        """send_fn(agent_id, task) -> coroutine that actually delivers task."""

        self._karma = karma
        self._queue = queue
        self._send_fn = send_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Main loop: pop tasks & dispatch."""

        while True:
            task = await self._queue.pop(timeout=5)
            if task is None:
                continue  # idle
            agent_id = await self._select_agent(task.task_type)
            if agent_id is None:
                # No agent registered; requeue & sleep
                await self._queue.push(task)
                await asyncio.sleep(1)
                continue
            await self._send_fn(agent_id, task)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _select_agent(self, task_type: str) -> str | None:
        candidates = STATIC_AGENT_REGISTRY.get(task_type)
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


aSYNC_SINGLETON_REDIS: Redis | None = None


async def get_redis() -> Redis:
    global aSYNC_SINGLETON_REDIS
    if aSYNC_SINGLETON_REDIS is None:
        aSYNC_SINGLETON_REDIS = aioredis.from_url(REDIS_URL, decode_responses=False)
    return aSYNC_SINGLETON_REDIS


async def create_scheduler(
    send_fn: Callable[[str, Task], asyncio.Future],
    *,
    karma: KarmaLedger | None = None,
) -> Scheduler:
    redis = await get_redis()
    queue = TaskQueue(redis)
    karma = karma or KarmaLedger.from_env()
    return Scheduler(karma, queue, send_fn) 