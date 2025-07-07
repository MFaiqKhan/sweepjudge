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
from app.utils.metrics_extract import extract_metrics

from .base import BaseAgent

logger = logging.getLogger(__name__)


class MetricianAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Extract_Metrics":
            return
        pdf_path_str: str | None = task.payload.get("pdf_path")
        if not pdf_path_str or not Path(pdf_path_str).exists():
            await self._emit_karma(self.agent_id, -1, reason="pdf-missing")
            return

        text = self._extract_text(Path(pdf_path_str))
        metrics = extract_metrics(text)
        metrics_json = [
            {"metric": m, "value": v, "dataset": d} for m, v, d in metrics
        ]

        part = DataPart(data=metrics_json)  # type: ignore[arg-type]
        artifact = Artifact(name="metrics", parts=[part])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        karma_delta = 2 if metrics_json else -1
        await self._emit_karma(self.agent_id, karma_delta, reason="metrics-parsed")

        # emit follow-up compare task, passing metrics so analyst can aggregate
        follow_task = Task(task_type="Compare_Methods", payload={"metrics": metrics_json})
        await self._emit_task(follow_task)

        logger.info("%s extracted %d metrics from %s", self.agent_id, len(metrics_json), pdf_path_str)

    def _extract_text(self, pdf_path: Path) -> str:
        try:
            reader = PyPDF2.PdfReader(str(pdf_path))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Metrician failed to read PDF: %s", exc)
            return "" 