"""Karma ledger – stores reputation updates in Postgres.

The ledger is append-only; each agent action records a delta. Aggregate
scores are computed on demand via SUM(delta).

This module keeps DB coupling minimal so it can be swapped for another
backend (e.g. Redis JSON or SQLite) without touching the business logic.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, MetaData, String, Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import select
from sqlalchemy.pool import NullPool


_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@db:5432/karma"


class _Tables:
    metadata = MetaData()

    karma = Table(
        "karma_events",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("agent_id", String(64), nullable=False, index=True),
        Column("delta", Integer, nullable=False),
        Column("reason", String(255), nullable=True),
        Column("task_id", String(128), nullable=True),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )


class KarmaLedger:
    """Lightweight async wrapper around the karma_events table."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )

    # ---------------------------------------------------------------------
    # Factory helpers
    # ---------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "KarmaLedger":
        db_url = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)
        print(f"Using DATABASE_URL: {db_url}")  # Debug print to check URL
        
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
        """Create tables if they don't exist (idempotent)."""

        async with self._engine.begin() as conn:
            await conn.run_sync(_Tables.metadata.create_all)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def add_delta(
        self,
        agent_id: str,
        delta: int,
        *,
        reason: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> None:
        async with self._sessionmaker() as sess:
            await sess.execute(
                _Tables.karma.insert().values(
                    agent_id=agent_id,
                    delta=delta,
                    reason=reason,
                    task_id=task_id,
                    created_at=_dt.datetime.utcnow(),
                )
            )
            await sess.commit()

    async def score(self, agent_id: str) -> int:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(_Tables.karma.c.delta).where(_Tables.karma.c.agent_id == agent_id)
            )
            return sum(r[0] for r in result) if result else 0

    async def top(self, limit: int = 10) -> list[tuple[str, int]]:
        """Return agents with highest karma scores."""

        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(
                    _Tables.karma.c.agent_id,
                    _Tables.karma.c.delta,
                )
            )
            # manual aggregation because SQLAlchemy async window funcs are verbose
            scores: dict[str, int] = {}
            for agent_id, delta in result:
                scores[agent_id] = scores.get(agent_id, 0) + delta
            return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit] 