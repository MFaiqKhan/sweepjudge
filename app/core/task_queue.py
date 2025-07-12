"""PostgreSQL-backed Task Queue for v2 architecture.

This replaces the Redis-based queue from v1. Instead of BLPOP, it uses
PostgreSQL's LISTEN/NOTIFY mechanism for event-driven task processing
with FOR UPDATE SKIP LOCKED for safe concurrent dequeuing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
# (Error , commented and not deleted just for reference) from sqlalchemy.ext.asyncio.connection import AsyncConnection There is no connection sub-package. AsyncConnection already comes from sqlalchemy.ext.asyncio.
from sqlalchemy.pool import NullPool  # Correct import path for NullPool

from app.core.models import DBTaskStatus, Task, TaskRecord
from app.core.tables import schema_creation_sql, tasks, agents

logger = logging.getLogger(__name__)

# How often to check for and retry stuck tasks (seconds)
TASK_RETRY_INTERVAL = int(os.getenv("TASK_RETRY_SEC", "60"))

# Tasks in_progress for this many seconds are eligible for retry
TASK_STUCK_THRESHOLD = int(os.getenv("TASK_STUCK_SEC", "300"))  # 5 minutes


class TaskQueue:
    """PostgreSQL-backed task queue using LISTEN/NOTIFY and FOR UPDATE SKIP LOCKED.
    
    This replaces the Redis-based queue in v1, providing durability and
    eliminating the need for a separate Redis instance.
    """
    
    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._connection: Optional[AsyncConnection] = None
        self._task_channel = "task_queue"
        self._listen_task: Optional[asyncio.Task] = None
        self._retry_task: Optional[asyncio.Task] = None
        self._new_task_event = asyncio.Event()
        # Track whether background listener/retry tasks have been started already.
        # This prevents multiple initialize() calls from creating duplicate tasks and
        # leaking connections when the orchestrator and scheduler both perform
        # initialisation.
        self._initialized: bool = False
        
    @classmethod
    def from_env(cls) -> TaskQueue:
        """Create a TaskQueue from the DATABASE_URL env var."""
        db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/karma")
        
        # Ensure we're using psycopg dialect for async support
        if not db_url.startswith("postgresql+psycopg://"):
            if db_url.startswith("postgresql://"):
                db_url = db_url.replace("postgresql://", "postgresql+psycopg://")
        
        # Create engine with PgBouncer compatibility settings
        engine_kwargs = {
            "echo": False,
            "connect_args": {"prepare_threshold": 0},
            "poolclass": NullPool,
        }
        
        engine = create_async_engine(db_url, **engine_kwargs)
        return cls(engine)
    
    async def create_schema(self) -> None:
        """Create the tasks table and notification triggers if they don't exist."""
        async with self._engine.begin() as conn:
            # Create the agents table first (required by tasks table foreign key)
            await conn.run_sync(lambda conn: agents.create(conn, checkfirst=True))
            
            # Then create the tasks table
            await conn.run_sync(lambda conn: tasks.create(conn, checkfirst=True))
            
            # Execute schema creation SQL
            for sql in schema_creation_sql:
                await conn.execute(text(sql))
    
    async def initialize(self) -> None:
        """Start listening for notifications and retrying stuck tasks."""
        # Avoid double-initialisation (e.g. orchestrator AND scheduler)
        if self._initialized:
            logger.debug("TaskQueue.initialize() called again – already initialised, ignoring")
            return

        # Create a persistent connection for the listener
        self._connection = await self._engine.connect()

        # No LISTEN command needed since we're using polling instead of LISTEN/NOTIFY
        # because PgBouncer doesn’t support it properly.

        # Start background tasks
        self._listen_task = asyncio.create_task(self._notification_listener())
        self._retry_task = asyncio.create_task(self._retry_stuck_tasks())

        self._initialized = True

        logger.info("TaskQueue initialised with polling (pgbouncer compatible mode)")
    
    async def close(self) -> None:
        """Close connection and stop background tasks."""
        if self._listen_task:
            self._listen_task.cancel()
            
        if self._retry_task:
            self._retry_task.cancel()
            
        if self._connection:
            await self._connection.close()
            self._connection = None

        # Allow the task queue to be initialised again after a clean shutdown
        self._initialized = False
    
    async def push(self, task: Task) -> None:
        """Push a task to the queue.
        
        This inserts a row into the tasks table, which triggers a notification
        that wakes up any listeners.
        """
        task_record = TaskRecord(
            id=task.id,
            task_type=task.task_type,
            payload=task.payload,
            status=DBTaskStatus.queued,
            session_id=task.session_id,
        )
        
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(tasks).values(
                    id=task_record.id,
                    task_type=task_record.task_type,
                    payload=task_record.payload,
                    status=task_record.status.value,
                    session_id=task_record.session_id,
                )
            )
            
        # The trigger will call pg_notify, and our listener will set this event
        logger.debug("Task %s pushed to queue", task.id)
    
    async def pop(self, timeout: Optional[int] = None) -> Optional[Task]:
        """Pop a task from the queue.
        
        This dequeues the oldest task with FOR UPDATE SKIP LOCKED to safely
        handle concurrent consumers.
        
        Args:
            timeout: How long to wait for a task (seconds). None means wait forever.
            
        Returns:
            Task if found, None if timeout reached with no tasks.
        """
        try:
            # Wait for the event to be set by the notification listener
            if timeout is None:
                # Wait indefinitely for a task
                while not self._new_task_event.is_set():
                    # Check if there's already a task in the queue
                    task = await self._try_dequeue_task()
                    if task:
                        return task
                    
                    # Wait for notification of new task
                    await self._new_task_event.wait()
                    self._new_task_event.clear()
            else:
                # Wait with timeout
                try:
                    # First try without waiting
                    task = await self._try_dequeue_task()
                    if task:
                        return task
                    
                    # Wait for notification
                    await asyncio.wait_for(self._new_task_event.wait(), timeout)
                    self._new_task_event.clear()
                    return await self._try_dequeue_task()
                except asyncio.TimeoutError:
                    # Check once more before giving up
                    return await self._try_dequeue_task()
                
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Error in pop: %s", exc)
            return None
    
    async def size(self) -> int:
        """Return the number of queued tasks."""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(func.count())
                .where(tasks.c.status == DBTaskStatus.queued.value)
            )
            return result.scalar_one()
    
    async def mark_completed(self, task_id: uuid.UUID, agent_id: str) -> None:
        """Mark a task as completed by an agent."""
        await self._update_task_status(task_id, DBTaskStatus.completed, agent_id)
    
    async def mark_failed(self, task_id: uuid.UUID, agent_id: str) -> None:
        """Mark a task as failed."""
        await self._update_task_status(task_id, DBTaskStatus.failed, agent_id)
    
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    
    async def _try_dequeue_task(self) -> Optional[Task]:
        """Try to dequeue a task with FOR UPDATE SKIP LOCKED."""
        async with self._engine.begin() as conn:
            # Find the oldest queued task and lock it
            result = await conn.execute(
                select(tasks)
                .where(tasks.c.status == DBTaskStatus.queued.value)
                .order_by(tasks.c.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            
            row = result.first()
            if not row:
                return None
                
            # Update status to in_progress
            await conn.execute(
                update(tasks)
                .where(tasks.c.id == row.id)
                .values(
                    status=DBTaskStatus.in_progress.value,
                    updated_at=dt.datetime.utcnow(),
                )
            )
            
            # Convert to Task model
            return Task(
                id=row.id,
                task_type=row.task_type,
                payload=row.payload,
                session_id=row.session_id,
            )
    
    async def _update_task_status(
        self, task_id: uuid.UUID, status: DBTaskStatus, agent_id: Optional[str]
    ) -> None:
        """Update a task's status."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(tasks)
                .where(tasks.c.id == task_id)
                .values(
                    status=status.value,
                    agent_id=agent_id,
                    updated_at=dt.datetime.utcnow(),
                )
            )
    
    async def _notification_listener(self) -> None:
        """Listen for notifications and set the event when a task is ready.
        
        Note: We're using polling instead of actual LISTEN/NOTIFY because
        pgbouncer doesn't properly support PostgreSQL's LISTEN/NOTIFY mechanism.
        This is less efficient but works with Supabase/pgbouncer environments.
        """
        if not self._connection:
            logger.error("No connection established for notification listener")
            return
            
        try:
            while True:
                try:
                    # Instead of waiting for notifications directly, we'll poll the queue
                    # This is less efficient but works with pgbouncer
                    await asyncio.sleep(0.5)  # Check every half second
                    
                    # Check if there are any tasks in the queue
                    count = await self.size()
                    if count > 0:
                        # Signal that a task is available
                        self._new_task_event.set()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception("Error in notification listener: %s", exc)
                    # Sleep to avoid tight loop on errors
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.debug("Notification listener cancelled")
    
    async def _retry_stuck_tasks(self) -> None:
        """Periodically check for and retry tasks that have been stuck in_progress."""
        try:
            while True:
                await asyncio.sleep(TASK_RETRY_INTERVAL)
                
                try:
                    cutoff = dt.datetime.utcnow() - dt.timedelta(seconds=TASK_STUCK_THRESHOLD)
                    
                    async with self._engine.begin() as conn:
                        # Find tasks that have been in_progress for too long
                        result = await conn.execute(
                            update(tasks)
                            .where(and_(
                                tasks.c.status == DBTaskStatus.in_progress.value,
                                tasks.c.updated_at < cutoff,
                            ))
                            .values(
                                status=DBTaskStatus.queued.value,
                                updated_at=dt.datetime.utcnow(),
                                agent_id=None,
                            )
                            .returning(tasks.c.id)
                        )
                        
                        retried_ids = [row.id for row in result]
                        if retried_ids:
                            logger.info("Retrying %d stuck tasks: %s", len(retried_ids), retried_ids)
                            # Set the event to wake up any waiters
                            self._new_task_event.set()
                            
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception("Error in retry_stuck_tasks: %s", exc)
        except asyncio.CancelledError:
            logger.debug("Retry stuck tasks loop cancelled") 