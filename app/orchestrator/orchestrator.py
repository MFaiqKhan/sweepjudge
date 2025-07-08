"""Main orchestrator script.

Runs all agents in-process, connects them via async queues, and uses the
Postgres-backed Scheduler to assign tasks.

v2 architecture:
- Uses PostgreSQL for both task queue and agent directory
- Agents register themselves with their capabilities (task types)
- Tasks are stored durably in the database
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict

from app.core import Task
from app.core.agent_directory import AgentDirectory
from app.core.karma import KarmaLedger
from app.core.task_queue import TaskQueue
from app.orchestrator.scheduler import Scheduler, create_scheduler

from app.agents.fetcher_agent import FetcherAgent
from app.agents.reader_agent import ReaderAgent
from app.agents.metrician_agent import MetricianAgent
from app.agents.analyst_agent import AnalystAgent
from app.agents.debater_agent import DebaterAgent
from app.agents.synthesiser_agent import SynthesiserAgent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Agent classes to instantiate
AGENT_CLASSES = {
    "fetcher-1": FetcherAgent,
    "reader-1": ReaderAgent,
    "metrician-1": MetricianAgent,
    "analyst-1": AnalystAgent,
    "debater": DebaterAgent,
    "synthesiser": SynthesiserAgent,
}


class OrchestratorRuntime:
    def __init__(self) -> None:
        # Create service components from environment
        self._ledger = KarmaLedger.from_env()
        self._agent_directory = AgentDirectory.from_env()
        self._task_queue = TaskQueue.from_env()
        
        # Create in-memory agent inboxes
        self._agent_inboxes: Dict[str, asyncio.Queue[Task]] = {
            aid: asyncio.Queue() for aid in AGENT_CLASSES
        }
        
        # Create agent instances
        self._agents = [
            cls(
                agent_id=aid,
                inbox=self._agent_inboxes[aid],
                emit_task=self.enqueue_task,
                emit_karma=self.add_karma,
                agent_directory=self._agent_directory,  # Pass agent directory for registration
            )
            for aid, cls in AGENT_CLASSES.items()
        ]
        self._scheduler: Scheduler | None = None

    # ------------------------------------------------------------------
    # Hooks passed to agents
    # ------------------------------------------------------------------

    async def enqueue_task(self, task: Task) -> None:
        """Enqueue a task for processing by the scheduler."""
        if self._task_queue is None:
            raise RuntimeError("Task queue not initialized")
        await self._task_queue.push(task)

    async def add_karma(self, agent_id: str, delta: int, reason: str | None = None) -> None:
        """Add a karma delta for an agent."""
        await self._ledger.add_delta(agent_id, delta, reason=reason)

    # ------------------------------------------------------------------
    # Send fn for scheduler -> agent inbox
    # ------------------------------------------------------------------

    async def _send_to_agent(self, agent_id: str, task: Task):
        """Send a task to an agent's in-process inbox."""
        inbox = self._agent_inboxes.get(agent_id)
        if inbox is None:
            logger.warning("Scheduler selected unknown agent %s", agent_id)
            # Could dynamically create an inbox for this agent, but for now just warn
            return
        await inbox.put(task)

    # ------------------------------------------------------------------
    async def start(self):
        """Initialize services and start all components."""
        # Create all needed database tables
        await self._ledger.create_schema()
        await self._agent_directory.create_schema()
        await self._task_queue.create_schema()
        
        # Create the scheduler with all dependencies
        self._scheduler = Scheduler(
            karma=self._ledger,
            queue=self._task_queue,
            agent_directory=self._agent_directory,
            send_fn=self._send_to_agent,
        )
        
        # Initialize the task queue (start listening for notifications)
        await self._task_queue.initialize()

        # Launch components as tasks
        tasks = [asyncio.create_task(self._scheduler.run_forever())]
        for agent in self._agents:
            tasks.append(asyncio.create_task(agent.run_forever()))

        logger.info("Orchestrator runtime started with %d agents", len(self._agents))
        await asyncio.gather(*tasks)


async def main():
    runtime = OrchestratorRuntime()
    await runtime.start()


if __name__ == "__main__":
    asyncio.run(main()) 