"""
Script to check the current status of all tasks in the database.
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

async def check_tasks():
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
        # Get all tasks with their status
        result = await conn.execute(
            text("""
                SELECT id, task_type, status, agent_id, created_at, updated_at 
                FROM tasks 
                ORDER BY created_at DESC
            """)
        )
        
        tasks = result.fetchall()
        print(f"Found {len(tasks)} total tasks")
        
        # Group by status
        status_counts = {}
        for task in tasks:
            status = task.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("\nTask Status Summary:")
        for status, count in status_counts.items():
            print(f"  {status}: {count}")
        
        print("\nRecent Tasks:")
        for task in tasks[:10]:  # Show last 10 tasks
            print(f"  {task.task_type} - {task.status} - {task.created_at} - Agent: {task.agent_id or 'None'}")

if __name__ == "__main__":
    asyncio.run(check_tasks()) 