"""AgentDirectory – Postgres-backed agent discovery service.

This replaces the static in-code registry from v1 with a dynamic
directory where agents register themselves and heartbeat to show
they are still alive.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import List, Optional

from sqlalchemy import and_, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.models import AgentRecord, AgentStatus
from app.core.tables import agents

logger = logging.getLogger(__name__)

# Default interval for agent heartbeats in seconds
DEFAULT_HEARTBEAT_INTERVAL = int(os.getenv("AGENT_HEARTBEAT_SEC", "30"))

# Agents that haven't heartbeated in this many seconds are considered inactive
STALE_AGENT_THRESHOLD = int(os.getenv("AGENT_STALE_SEC", "90"))


class AgentDirectory:
    """Agent discovery service backed by Postgres.
    
    Agents register themselves with their capabilities (task_types they can handle)
    and heartbeat periodically to show they're alive.
    
    The Scheduler uses this to find the best agent for a task.
    """
    
    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._heartbeat_tasks = {}  # agent_id -> asyncio.Task
        
    @classmethod
    def from_env(cls) -> AgentDirectory:
        """Create an AgentDirectory from the DATABASE_URL env var."""
        db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/karma")
        engine = create_async_engine(db_url, echo=False)
        return cls(engine)
        
    async def create_schema(self) -> None:
        """Create the agents table if it doesn't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(lambda conn: agents.create(conn, checkfirst=True))
    
    async def register(self, agent_id: str, task_types: List[str]) -> None:
        """Register an agent with its capabilities.
        
        If the agent already exists, update its task_types and mark it active.
        """
        async with self._engine.begin() as conn:
            # Try to insert, on conflict update the task_types and last_heartbeat
            stmt = insert(agents).values(
                id=agent_id,
                task_types=task_types,
                last_heartbeat=dt.datetime.utcnow(),
                status=AgentStatus.active.value,
            ).on_conflict_do_update(
                index_elements=[agents.c.id],
                set_={
                    "task_types": task_types,
                    "last_heartbeat": dt.datetime.utcnow(),
                    "status": AgentStatus.active.value,
                }
            )
            await conn.execute(stmt)
        
        # Start a heartbeat task for this agent if not already running
        if agent_id not in self._heartbeat_tasks:
            self._heartbeat_tasks[agent_id] = asyncio.create_task(
                self._heartbeat_loop(agent_id)
            )
        
        logger.info("Agent %s registered with task_types %s", agent_id, task_types)
    
    async def heartbeat(self, agent_id: str) -> None:
        """Update agent's last_heartbeat timestamp."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(agents)
                .where(agents.c.id == agent_id)
                .values(
                    last_heartbeat=dt.datetime.utcnow(),
                    status=AgentStatus.active.value,
                )
            )
    
    async def unregister(self, agent_id: str) -> None:
        """Mark an agent as inactive but keep its record."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(agents)
                .where(agents.c.id == agent_id)
                .values(status=AgentStatus.inactive.value)
            )
            
        # Cancel the heartbeat task if it exists
        if agent_id in self._heartbeat_tasks:
            self._heartbeat_tasks[agent_id].cancel()
            del self._heartbeat_tasks[agent_id]
            
        logger.info("Agent %s unregistered", agent_id)
    
    async def get_candidates(self, task_type: str) -> List[str]:
        """Get all active agents that can handle a given task type."""
        cutoff = dt.datetime.utcnow() - dt.timedelta(seconds=STALE_AGENT_THRESHOLD)
        
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(agents.c.id)
                .where(and_(
                    agents.c.task_types.contains([task_type]),
                    agents.c.status == AgentStatus.active.value,
                    agents.c.last_heartbeat >= cutoff
                ))
            )
            return [row[0] for row in result]
    
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    
    async def _heartbeat_loop(self, agent_id: str) -> None:
        """Send periodic heartbeats for an agent."""
        try:
            while True:
                await asyncio.sleep(DEFAULT_HEARTBEAT_INTERVAL)
                await self.heartbeat(agent_id)
        except asyncio.CancelledError:
            logger.debug("Heartbeat loop for %s cancelled", agent_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Heartbeat for agent %s failed: %s", agent_id, exc) 