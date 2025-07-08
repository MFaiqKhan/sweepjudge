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

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.core import Task
from app.core.task_queue import TaskQueue
from app.orchestrator.orchestrator import OrchestratorRuntime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_PDF = "https://arxiv.org/pdf/2106.09685.pdf"


async def enqueue_initial_task(url: str):
    """Insert the first Fetch_Paper task into the durable queue."""
    queue = TaskQueue.from_env()
    await queue.create_schema()  # idempotent
    task = Task(task_type="Fetch_Paper", payload={"url": url})
    await queue.push(task)
    logger.info("Enqueued Fetch_Paper for %s", url)


async def main():
    parser = argparse.ArgumentParser(description="Run Karma Sandbox v2 pipeline")
    parser.add_argument("--url", default=DEFAULT_PDF, help="PDF URL to fetch & analyse")
    args = parser.parse_args()

    runtime = OrchestratorRuntime()

    # Run orchestrator concurrently with enqueue helper
    await asyncio.gather(runtime.start(), enqueue_initial_task(args.url))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0) 