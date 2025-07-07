#!/usr/bin/env python
"""Kick-off script for local dev.

Usage:
  python scripts/start_dev.py --url https://arxiv.org/pdf/2106.09685.pdf

It boots the orchestrator runtime in the background and enqueues the
initial Fetch_Paper task.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.core import Task
from app.core.karma import KarmaLedger
from app.orchestrator.orchestrator import OrchestratorRuntime
from app.orchestrator.scheduler import get_redis, QUEUE_KEY

logging.basicConfig(level=logging.INFO)

DEFAULT_PDF = "https://arxiv.org/pdf/2106.09685.pdf"


async def enqueue_initial_task(url: str):
    redis = await get_redis()
    task = Task(task_type="Fetch_Paper", payload={"url": url})
    await redis.rpush(QUEUE_KEY, task.model_dump_json())
    logging.info("Enqueued Fetch_Paper for %s", url)


async def main():
    parser = argparse.ArgumentParser(description="Run Karma Sandbox MVP pipeline")
    parser.add_argument("--url", default=DEFAULT_PDF, help="PDF URL to fetch")
    args = parser.parse_args()

    # Clear existing queue for clean run
    redis = await get_redis()
    await redis.delete(QUEUE_KEY)

    runtime = OrchestratorRuntime()

    # start runtime concurrently with enqueue
    await asyncio.gather(runtime.start(), enqueue_initial_task(args.url))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0) 