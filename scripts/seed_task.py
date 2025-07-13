"""
A simple command-line utility to seed the task queue with an initial task.
This is the entry point for starting a new paper processing pipeline.

Example:
  python scripts/seed_task.py "https://arxiv.org/pdf/2305.14314"
"""
import asyncio
import os

from dotenv import load_dotenv
import typer

from app.core import Task
from app.core.task_queue import TaskQueue

# ---------------------------------------------------------------------------
# Windows event-loop compatibility for psycopg / asyncpg
# ---------------------------------------------------------------------------

if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load environment variables so DATABASE_URL is available
load_dotenv()


async def add_task(url: str) -> None:
    """Create a Fetch_Paper task and push it via TaskQueue so status is 'queued'."""

    import uuid as _uuid

    sess_id = _uuid.uuid4().hex
    task = Task(
        task_type="Fetch_Paper",
        payload={"url": url},
        session_id=sess_id,
    )

    queue = TaskQueue.from_env()
    await queue.create_schema()  # idempotent
    await queue.push(task)
    # Close background tasks gracefully
    await queue.close()

    print(f"✅ Task {task.id} successfully added to the queue.")


def main(url: str = typer.Argument(..., help="Full URL to the PDF paper.")) -> None:
    print(f"Seeding the task queue for URL: {url}")
    asyncio.run(add_task(url))


if __name__ == "__main__":
    typer.run(main) 