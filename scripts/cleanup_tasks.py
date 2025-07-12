
import asyncio
import os
import platform
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

load_dotenv()  # Load environment variables from .env

# Set event loop policy only on Windows for compatibility with psycopg
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def cleanup_stuck_tasks():
    db_url = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@db:5432/karma")
    
    # Ensure psycopg dialect
    if not db_url.startswith("postgresql+psycopg://"):
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg://")
    
    # Create engine with PgBouncer compatibility
    engine = create_async_engine(
        db_url,
        echo=True,
        connect_args={"prepare_threshold": 0},
        poolclass=NullPool,
    )
    
    async with engine.begin() as conn:
        # First, count the tasks to delete
        count_result = await conn.execute(
            text("SELECT COUNT(*) FROM tasks WHERE status IN ('queued', 'in_progress')")
        )
        count = count_result.scalar_one()
        print(f"Found {count} stuck tasks to delete.")
        
        if count > 0:
            # Delete them
            await conn.execute(
                text("DELETE FROM tasks WHERE status IN ('queued', 'in_progress')")
            )
            print(f"Deleted {count} stuck tasks.")
        else:
            print("No stuck tasks found.")

if __name__ == "__main__":
    asyncio.run(cleanup_stuck_tasks())
 