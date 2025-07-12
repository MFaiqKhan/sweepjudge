"""PreFilterAgent – fast heuristic page filter to reduce LLM tokens

Input payload
-------------
{
    "pdf_path": "/abs/path/file.pdf"
}

Configurable options (via self.config)
-------------------------------------
filter_keywords : List[str]   – keywords to boost when scoring pages
max_pages       : int         – how many pages to keep (default 8)

Output
------
1. Completes its own task with artifact `filtered_pages` (text)
2. Emits new task `Extract_Metrics` with payload {"text_snippet": <filtered_text>}
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List

from app.core import Artifact, Task, TaskStatus, TextPart
from app.utils.pdf_filter import filter_metric_pages, DEFAULT_KEYWORDS

from .base import BaseAgent

logger = logging.getLogger(__name__)


class PreFilterAgent(BaseAgent):
    TASK_TYPES = ["Filter_Pages"]

    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Filter_Pages":
            return

        pdf_path_str: str | None = task.payload.get("pdf_path")
        if not pdf_path_str or not Path(pdf_path_str).exists():
            await self._emit_karma(self.agent_id, -1, reason="pdf-missing")
            return
        pdf_path = Path(pdf_path_str)

        # Read config
        keywords: List[str] = self.config.get("filter_keywords", DEFAULT_KEYWORDS)
        max_pages: int = int(self.config.get("max_pages", 8))
        logger.info(
            "PreFilter %s scanning %s (keywords=%s, max_pages=%d)",
            self.agent_id,
            pdf_path.name,
            keywords,
            max_pages,
        )

        filtered_text = filter_metric_pages(pdf_path, keywords=keywords, max_pages=max_pages)

        if not filtered_text.strip():
            # Fallback – nothing extracted, hand off full PDF path instead
            logger.warning("PreFilter %s produced empty snippet – falling back to full pdf", self.agent_id)
            follow_payload: dict[str, Any] = {"pdf_path": str(pdf_path)}
        else:
            follow_payload = {"text_snippet": filtered_text}

        # Artifact for traceability
        artifact = Artifact(name="filtered_pages", parts=[TextPart(text=filtered_text or "")])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        # Emit next task for Metrician
        follow_task = Task(task_type="Extract_Metrics", payload=follow_payload)
        await self._emit_task(follow_task)

        # Reward modestly for speed (no LLM cost)
        await self._emit_karma(self.agent_id, +1, reason="prefilter-done")

        logger.info(
            "%s filtered pdf %s → %d chars snippet", self.agent_id, pdf_path.name, len(filtered_text)
        ) 