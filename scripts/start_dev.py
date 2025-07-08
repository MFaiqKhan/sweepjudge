#!/usr/bin/env python
"""DEPRECATED helper (v1).

Since v2 replaced Redis with Postgres, this script is no longer runnable.
It remains here *commented out* purely for historical reference.  Use
`scripts/run_pipeline.py` for the modern entry-point.
"""

import sys
print("start_dev.py is obsolete – use scripts/run_pipeline.py instead.")
sys.exit(1)

# ---------------------------------------------------------------------------
# Legacy implementation (Redis-based) – kept for documentation purposes only
# ---------------------------------------------------------------------------
#
# from __future__ import annotations
#
# import argparse
# import asyncio
# import logging
# import sys
#
# from app.core import Task
# from app.orchestrator.orchestrator import OrchestratorRuntime
# from app.orchestrator.scheduler import get_redis, QUEUE_KEY
#
# logging.basicConfig(level=logging.INFO)
# DEFAULT_PDF = "https://arxiv.org/pdf/2106.09685.pdf"
#
# async def enqueue_initial_task(url: str):
#     redis = await get_redis()
#     task = Task(task_type="Fetch_Paper", payload={"url": url})
#     await redis.rpush(QUEUE_KEY, task.model_dump_json())
#     logging.info("Enqueued Fetch_Paper for %s", url)
#
# async def main():
#     parser = argparse.ArgumentParser(description="Run Karma Sandbox MVP pipeline (v1)")
#     parser.add_argument("--url", default=DEFAULT_PDF, help="PDF URL to fetch")
#     args = parser.parse_args()
#
#     # Clear existing queue for clean run
#     redis = await get_redis()
#     await redis.delete(QUEUE_KEY)
#
#     runtime = OrchestratorRuntime()
#     await asyncio.gather(runtime.start(), enqueue_initial_task(args.url))
#
# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         sys.exit(0) 