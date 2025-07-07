"""Main orchestrator script.

Runs all agents in-process, connects them via async queues, and uses the
Redis-backed Scheduler to assign tasks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict

from app.core import Task
from app.core.karma import KarmaLedger
from app.orchestrator.scheduler import Scheduler, create_scheduler

from app.agents.fetcher_agent import FetcherAgent
from app.agents.reader_agent import ReaderAgent
from app.agents.metrician_agent import MetricianAgent
from app.agents.analyst_agent import AnalystAgent
from app.agents.debater_agent import DebaterAgent
from app.agents.synthesiser_agent import SynthesiserAgent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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
        self._ledger = KarmaLedger.from_env()
        self._agent_inboxes: Dict[str, asyncio.Queue[Task]] = {
            aid: asyncio.Queue() for aid in AGENT_CLASSES
        }
        self._agents = [
            cls(
                agent_id=aid,
                inbox=self._agent_inboxes[aid],
                emit_task=self.enqueue_task,
                emit_karma=self.add_karma,
            )
            for aid, cls in AGENT_CLASSES.items()
        ]
        self._scheduler: Scheduler | None = None

    # ------------------------------------------------------------------
    # Hooks passed to agents
    # ------------------------------------------------------------------

    async def enqueue_task(self, task: Task) -> None:
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialised")
        await self._scheduler._queue.push(task)  # pylint: disable=protected-access

    async def add_karma(self, agent_id: str, delta: int, reason: str | None = None) -> None:
        await self._ledger.add_delta(agent_id, delta, reason=reason)

    # ------------------------------------------------------------------
    # Send fn for scheduler -> agent inbox
    # ------------------------------------------------------------------

    async def _send_to_agent(self, agent_id: str, task: Task):
        inbox = self._agent_inboxes.get(agent_id)
        if inbox is None:
            logger.warning("Scheduler selected unknown agent %s", agent_id)
            return
        await inbox.put(task)

    # ------------------------------------------------------------------
    async def start(self):
        await self._ledger.create_schema()
        self._scheduler = await create_scheduler(self._send_to_agent, karma=self._ledger)

        # launch components
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