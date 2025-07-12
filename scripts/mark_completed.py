"""
Script to mark all in_progress tasks as completed.
The agents processed these tasks but didn't update the database status.
"""

import asyncio
import os
import platform
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

load_dotenv()

# Set event loop policy only on Windows for compatibility with psycopg
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def mark_completed():
    db_url = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@db:5432/karma")
    
    # Ensure psycopg dialect
    if not db_url.startswith("postgresql+psycopg://"):
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg://")
    
    # Create engine with PgBouncer compatibility
    engine = create_async_engine(
        db_url,
        echo=False,
        connect_args={"prepare_threshold": 0},
        poolclass=NullPool,
    )
    
    async with engine.begin() as conn:
        # Count in_progress tasks
        count_result = await conn.execute(
            text("SELECT COUNT(*) FROM tasks WHERE status = 'in_progress'")
        )
        count = count_result.scalar_one()
        print(f"Found {count} tasks in 'in_progress' status")
        
        if count > 0:
            # Mark them as completed
            await conn.execute(
                text("UPDATE tasks SET status = 'completed' WHERE status = 'in_progress'")
            )
            print(f"Marked {count} tasks as completed")
        else:
            print("No in_progress tasks found")

if __name__ == "__main__":
    asyncio.run(mark_completed()) 