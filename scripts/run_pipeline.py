#!/usr/bin/env python
"""Run the full v2 pipeline locally.

Example:
  python scripts/run_pipeline.py \
      --url https://arxiv.org/pdf/2106.09685.pdf

What it does:
1. Ensures required Postgres tables exist (tasks, agents, karma).
2. Starts the orchestrator runtime (scheduler + agents).
3. Enqueues an initial `Fetch_Paper` task so the pipeline shows activity.

Environment vars used:
  DATABASE_URL         – Postgres connection string
  OPENROUTER_API_KEY   – Your OpenRouter key (needed by Reader & Debater)
"""

# """
# This entire script is part of the V2 architecture and is now DEPRECATED.
# It is preserved here for historical reference only.
#
# The V3 architecture uses a service-based approach. To run the system:
# 1. Start the orchestrator: `python app/orchestrator/orchestrator.py`
# 2. Spawn agents via the CLI: `python scripts/manage_swarm.py add ...`
# 3. Seed tasks via the CLI: `python scripts/seed_task.py <url>`
# """

# from __future__ import annotations

# import asyncio
# import logging
# from typing import Any, Coroutine, Dict, List

# from app.agents.analyst_agent import AnalystAgent
# from app.agents.base import BaseAgent
# from app.agents.debater_agent import DebaterAgent
# from app.agents.fetcher_agent import FetcherAgent
# from app.agents.metrician_agent import MetricianAgent
# from app.agents.reader_agent import ReaderAgent
# from app.agents.synthesiser_agent import SynthesiserAgent
# from app.core import (
#     AgentDirectory,
#     EmitKarmaFn,
#     EmitTaskFn,
#     KarmaLedger,
#     Task,
#     TaskQueue,
# )
# from app.orchestrator.scheduler import Scheduler

# # Setup basic logging
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
# logger = logging.getLogger(__name__)


# async def main():
#     # ------------------------------------------------------------------
#     # Setup: Create all the core services and agents
#     # ------------------------------------------------------------------
#     # In a real system these would be loaded from env vars
#     task_queue = TaskQueue.from_env()
#     karma_ledger = KarmaLedger.from_env()
#     agent_directory = AgentDirectory.from_env()

#     # In-memory queues for direct agent communication
#     agent_inboxes: Dict[str, asyncio.Queue] = {}

#     async def send_to_agent(agent_id: str, task: Task):
#         """A send function that the scheduler can use to route tasks."""
#         if agent_id not in agent_inboxes:
#             # This can happen if an agent is stopped/crashes
#             logger.warning(
#                 f"Scheduler tried to send to unknown agent '{agent_id}'. Re-queueing task."
#             )
#             await task_queue.push(task)
#             return
#         await agent_inboxes[agent_id].put(task)

#     # The scheduler is the "brain" that assigns tasks from the queue
#     scheduler = Scheduler(
#         karma=karma_ledger,
#         queue=task_queue,
#         agent_directory=agent_directory,
#         send_fn=send_to_agent,
#     )

#     # This function will be passed to agents so they can create new tasks
#     emit_task: EmitTaskFn = task_queue.push
#     # This will be passed to agents so they can +/- karma
#     emit_karma: EmitKarmaFn = karma_ledger.add_delta

#     agents: List[BaseAgent] = [
#         FetcherAgent("fetcher-1", inbox=asyncio.Queue(), emit_task=emit_task, emit_karma=emit_karma, agent_directory=agent_directory),
#         ReaderAgent("reader-1", inbox=asyncio.Queue(), emit_task=emit_task, emit_karma=emit_karma, agent_directory=agent_directory),
#         MetricianAgent("metrician-1", inbox=asyncio.Queue(), emit_task=emit_task, emit_karma=emit_karma, agent_directory=agent_directory),
#         AnalystAgent("analyst-1", inbox=asyncio.Queue(), emit_task=emit_task, emit_karma=emit_karma, agent_directory=agent_directory),
#         DebaterAgent("debater-1", inbox=asyncio.Queue(), emit_task=emit_task, emit_karma=emit_karma, agent_directory=agent_directory),
#         SynthesiserAgent("synth-1", inbox=asyncio.Queue(), emit_task=emit_task, emit_karma=emit_karma, agent_directory=agent_directory),
#     ]
#     # Link agent IDs to their inboxes for the scheduler's send_fn
#     for agent in agents:
#         agent_inboxes[agent.agent_id] = agent._inbox


#     # ------------------------------------------------------------------
#     # DB setup: Create schemas if they don't exist
#     # ------------------------------------------------------------------
#     await task_queue.create_schema()
#     await karma_ledger.create_schema()
#     await agent_directory.create_schema()

#     # ------------------------------------------------------------------
#     # Initialisation: Add a starting task to the queue if it's empty
#     # ------------------------------------------------------------------
#     if await task_queue.is_empty():
#         # This is the starting point for the whole research pipeline
#         initial_task = Task(
#             task_type="Fetch_Paper",
#             payload={"url": "https://arxiv.org/pdf/2305.14314.pdf"}, # Llama 2 paper
#         )
#         await task_queue.push(initial_task)
#         logger.info("Task queue was empty. Seeded with initial 'Fetch_Paper' task.")


#     # ------------------------------------------------------------------
#     # Main loop: Start all agents and the scheduler
#     # ------------------------------------------------------------------
#     try:
#         # Start all agents as background tasks
#         agent_tasks: List[Coroutine[Any, Any, None]] = [
#             agent.run_forever() for agent in agents
#         ]
#         # Start the scheduler as a background task
#         all_tasks = agent_tasks + [scheduler.run_forever()]
#         logger.info(f"Starting {len(agents)} agents and 1 scheduler...")
#         await asyncio.gather(*all_tasks)

#     except KeyboardInterrupt:
#         logger.info("Shutdown signal received.")
#     finally:
#         # In a real system you'd have more graceful shutdown logic
#         logger.info("Pipeline stopped.")


# if __name__ == "__main__":
#     # In Python 3.8+ you can use asyncio.run(main())
#     asyncio.run(main()) 