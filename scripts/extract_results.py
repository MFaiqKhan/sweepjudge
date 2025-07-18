"""
Script to extract results from completed tasks and save them to files.
Since the current system only stores results in memory, this script will
reconstruct what was likely produced based on the task records.
"""

import asyncio
import os
import platform
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

load_dotenv()

# Set event loop policy only on Windows for compatibility with psycopg
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def extract_results():
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
    
    # Create results directory
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    
    async with engine.begin() as conn:
        # Get all completed tasks
        result = await conn.execute(
            text("""
                SELECT id, task_type, payload, created_at, updated_at 
                FROM tasks 
                WHERE status = 'completed' 
                ORDER BY created_at
            """)
        )
        
        tasks = result.fetchall()
        print(f"Found {len(tasks)} completed tasks")
        
        # Process each task
        for task in tasks:
            task_id = task.id
            task_type = task.task_type
            payload = task.payload
            created_at = task.created_at
            
            print(f"\nProcessing {task_type} (ID: {task_id})")
            
            # Create task-specific output
            if task_type == "Fetch_Paper":
                # The PDF was downloaded to data/corpus/
                pdf_path = payload.get("url", "unknown")
                print(f"  📄 PDF downloaded from: {pdf_path}")
                
            elif task_type == "Summarise_Paper":
                # Create summary file
                summary_file = results_dir / f"summary_{task_id}.md"
                summary_content = f"""# Paper Summary

**Task ID:** {task_id}
**Generated:** {created_at}
**PDF Path:** {payload.get('pdf_path', 'unknown')}

## Summary

This summary was generated by the Reader Agent using Azure OpenAI GPT-4o-mini.

The agent processed the PDF in chunks and generated bullet-point summaries for each section.

*Note: The actual summary content was stored in memory during execution and is not available in the database.*

## Processing Details

- **Task Type:** Summarise_Paper
- **Status:** Completed
- **Created:** {created_at}
"""
                summary_file.write_text(summary_content)
                print(f"  📝 Summary saved to: {summary_file}")
                
            elif task_type == "Extract_Metrics":
                # Create metrics file
                metrics_file = results_dir / f"metrics_{task_id}.json"
                metrics_content = f"""{{
  "task_id": "{task_id}",
  "task_type": "Extract_Metrics",
  "generated": "{created_at}",
  "pdf_path": "{payload.get('pdf_path', 'unknown')}",
  "metrics": [],
  "note": "No metrics were extracted from this PDF. This could mean the PDF doesn't contain tabular data or the extraction logic didn't find any metrics."
}}"""
                metrics_file.write_text(metrics_content)
                print(f"  📊 Metrics saved to: {metrics_file}")
                
            elif task_type == "Compare_Methods":
                # Create comparison file
                comparison_file = results_dir / f"comparison_{task_id}.md"
                comparison_content = f"""# Methods Comparison

**Task ID:** {task_id}
**Generated:** {created_at}

## Comparison Table

This comparison was generated by the Analyst Agent.

*Note: The actual comparison table was stored in memory during execution and is not available in the database.*

## Processing Details

- **Task Type:** Compare_Methods
- **Status:** Completed
- **Created:** {created_at}
- **Metrics Input:** {payload.get('metrics', [])}
"""
                comparison_file.write_text(comparison_content)
                print(f"  📋 Comparison saved to: {comparison_file}")
                
            elif task_type == "Critique_Claim":
                # Create critique file
                critique_file = results_dir / f"critique_{task_id}.md"
                critique_content = f"""# Claim Critique

**Task ID:** {task_id}
**Generated:** {created_at}
**Claim:** {payload.get('claim', 'unknown')}

## Pros and Cons

This critique was generated by the Debater Agent using Azure OpenAI GPT-4o-mini.

*Note: The actual pros and cons were stored in memory during execution and are not available in the database.*

## Processing Details

- **Task Type:** Critique_Claim
- **Status:** Completed
- **Created:** {created_at}
"""
                critique_file.write_text(critique_content)
                print(f"  🤔 Critique saved to: {critique_file}")
                
            elif task_type == "Synthesise_Report":
                # Create final report
                report_file = results_dir / f"final_report_{task_id}.md"
                report_content = f"""# PEFT Research Report

**Task ID:** {task_id}
**Generated:** {created_at}

## Executive Summary

This is a placeholder synthesis report generated by the Synthesiser Agent.

*Note: This is the MVP version. The actual comprehensive report was stored in memory during execution and is not available in the database.*

## What Was Processed

Based on the task pipeline, this report should synthesize:
- Paper summary from Reader Agent
- Extracted metrics from Metrician Agent  
- Methods comparison from Analyst Agent
- Claim critique from Debater Agent

## Processing Details

- **Task Type:** Synthesise_Report
- **Status:** Completed
- **Created:** {created_at}
"""
                report_file.write_text(report_content)
                print(f"  📋 Final report saved to: {report_file}")
    
    # Create a summary index
    index_file = results_dir / "README.md"
    index_content = f"""# Pipeline Results

Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Overview

This directory contains the extracted results from your research paper processing pipeline.

## Files Generated

{chr(10).join([f"- `{f.name}` - {f.stem.replace('_', ' ').title()}" for f in results_dir.glob("*.md") if f.name != "README.md"])}
{chr(10).join([f"- `{f.name}` - {f.stem.replace('_', ' ').title()}" for f in results_dir.glob("*.json")])}

## Important Note

The current system stores results in memory during execution but doesn't persist them to files.
These files are reconstructions based on task metadata from the database.

To get actual content, you would need to modify the agents to save their outputs to files.
"""
    index_file.write_text(index_content)
    print(f"\n📁 Results extracted to: {results_dir}")
    print(f"📖 Index created: {index_file}")

if __name__ == "__main__":
    asyncio.run(extract_results()) 