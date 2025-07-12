"""
A simple command-line utility to seed the task queue with an initial task.
This is the entry point for starting a new paper processing pipeline.

Example:
  python scripts/seed_task.py "https://arxiv.org/pdf/2305.14314"
"""
import asyncio
import os
import uuid
from typing import Dict, Any

import asyncpg
from dotenv import load_dotenv
import typer

# Load environment variables from .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def add_task_to_db(task: Dict[str, Any]):
    """Connects to the database and inserts a new task."""
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL environment variable not set.")
        print("Please create a .env file with the database connection string.")
        raise typer.Exit(1)
        
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            INSERT INTO tasks (id, task_type, payload, status, created_at, updated_at)
            VALUES ($1, $2, $3, 'pending', NOW(), NOW())
            """,
            task["id"],
            task["task_type"],
            str(task["payload"]),  # Ensure payload is a string
        )
        print(f"✅ Task {task['id']} successfully added to the queue.")
    except Exception as e:
        print(f"❌ Failed to add task to the database: {e}")
    finally:
        await conn.close()

def main(
    url: str = typer.Argument(..., help="The full URL to the PDF paper to process."),
):
    """
    Creates a 'Fetch_Paper' task and submits it to the database queue.
    """
    print(f"Seeding the queue with a new 'Fetch_Paper' task for URL: {url}")
    
    task_id = uuid.uuid4()
    task = {
        "id": task_id,
        "task_type": "Fetch_Paper",
        "payload": {"url": url},
    }
    
    asyncio.run(add_task_to_db(task))

if __name__ == "__main__":
    typer.run(main) 