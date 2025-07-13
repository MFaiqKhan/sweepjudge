"""MetricianAgent – parses metrics from PDF text.

Input: {"pdf_path": str}
Outputs Artifact with JSON metrics and next task Compare_Methods
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List

import PyPDF2

from app.core import Artifact, DataPart, Task, TaskStatus
from app.utils.metrics_extract import extract_metrics, METRIC_PATTERNS

from .base import BaseAgent

logger = logging.getLogger(__name__)


class MetricianAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Extract_Metrics":
            return

        pdf_path_str: str | None = None

        # Branch 1: we already have pre-filtered text snippet
        if "text_snippet" in task.payload:
            text = task.payload["text_snippet"]
            logger.info(
                "Metrician %s received pre-filtered snippet (%d chars)",
                self.agent_id,
                len(text),
            )
        else:
            # Fallback: read full PDF
            pdf_path_str = task.payload.get("pdf_path")
            if not pdf_path_str or not Path(pdf_path_str).exists():
                await self._emit_karma(self.agent_id, -1, reason="pdf-missing")
                logger.error(f"PDF not found at path: {pdf_path_str}")
                return

            text = self._extract_text(Path(pdf_path_str))

        # Debug: log a sample of the text to verify extraction
        text_sample = text[:500] + "..." if len(text) > 500 else text
        logger.info(f"Extracted text sample: {text_sample}")
        
        # Check for custom patterns in the agent's config
        custom_patterns = self.config.get("metric_patterns")
        if custom_patterns:
            logger.info(f"Using custom metric patterns for agent {self.agent_id}")
            patterns = [(p["metric"], p["pattern"]) for p in custom_patterns]
        else:
            patterns = METRIC_PATTERNS

        # Extract metrics from text
        metrics = extract_metrics(text, patterns=patterns)
        logger.info(f"Found {len(metrics)} metrics in the PDF")
        
        # Convert to JSON format
        metrics_json = [
            {"metric": m, "value": v, "dataset": d} for m, v, d in metrics
        ]

        # Add metrics to task payload for persistence
        task.payload["metrics"] = metrics_json
        
        # Create artifact with metrics data
        part = DataPart(data=metrics_json)  # type: ignore[arg-type]
        artifact = Artifact(name="metrics", parts=[part])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        # Adjust karma based on success
        karma_delta = 2 if metrics_json else -1
        await self._emit_karma(self.agent_id, karma_delta, reason="metrics-parsed")

        # Forward metrics for downstream agents
        follow_payload: dict[str, Any] = {
            "metrics": metrics_json,
        }
        if "summary" in task.payload:
            follow_payload["summary"] = task.payload["summary"]
        if pdf_path_str:
            follow_payload["pdf_path"] = pdf_path_str
            
        src_desc = pdf_path_str if pdf_path_str else "snippet"

        # Create a follow-up task with a deterministic ID based on the session
        # This helps prevent duplicate tasks when multiple agents emit similar tasks
        import hashlib
        import uuid
        
        # Create a deterministic task ID based on session and task type
        task_id_seed = f"{task.session_id}_Compare_Methods" if task.session_id else f"Compare_Methods_{pdf_path_str}"
        task_id_hash = hashlib.md5(task_id_seed.encode()).hexdigest()
        task_id = uuid.UUID(task_id_hash[:32])
        
        # Check if this task already exists to prevent duplicates
        task_exists = False
        if self._task_queue:
            try:
                task_exists = await self._task_queue.task_exists(task_id)
            except Exception as exc:
                logger.warning(f"Failed to check if task exists: {exc}")
        
        if not task_exists:
            follow_task = Task(
                id=task_id,
                task_type="Compare_Methods", 
                payload=follow_payload, 
                session_id=task.session_id
            )
            await self._emit_task(follow_task)
            logger.info("%s extracted %d metrics from %s and emitted Compare_Methods task", 
                      self.agent_id, len(metrics_json), src_desc)
        else:
            logger.info("%s extracted %d metrics from %s but Compare_Methods task already exists", 
                      self.agent_id, len(metrics_json), src_desc)

    def _extract_text(self, pdf_path: Path) -> str:
        """Extract text from PDF with better error handling and page tracking."""
        try:
            reader = PyPDF2.PdfReader(str(pdf_path))
            text_parts = []
            
            # Process each page
            for i, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ""
                    if page_text.strip():  # Only add non-empty pages
                        # Add page marker to help with debugging
                        text_parts.append(f"--- PAGE {i+1} ---")
                        text_parts.append(page_text)
                except Exception as page_exc:
                    logger.warning(f"Failed to extract text from page {i+1}: {page_exc}")
            
            full_text = "\n".join(text_parts)
            logger.info(f"Extracted {len(full_text)} characters from {len(reader.pages)} pages")
            return full_text
            
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Metrician failed to read PDF: %s", exc)
            return "" 