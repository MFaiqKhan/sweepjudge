"""AnalystAgent – compares methods across metric lists.

Input payload expects 'metrics' key with list of metrics for one paper OR list of lists.
If multiple lists provided, builds combo table; else single list table.
Outputs markdown artifact and emits Critique_Claim task.
"""

from __future__ import annotations

import logging
from typing import Any, List

from app.core import Artifact, Task, TaskStatus, TextPart
from app.utils.compare_tools import metrics_to_markdown

from .base import BaseAgent

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Compare_Methods":
            return

        payload = task.payload
        metrics_input = payload.get("metrics")
        if metrics_input is None:
            await self._emit_karma(self.agent_id, -1, reason="no-metrics")
            return

        # --- Specialization: Filter for focus_metrics if configured ---
        focus_metrics = self.config.get("focus_metrics")
        if focus_metrics:
            logger.info(f"Analyst {self.agent_id} filtering for metrics: {focus_metrics}")
            
            # This logic assumes metrics_input is a list of dicts
            # and we need to handle the list of lists case as well.
            def filter_metrics(metrics: List[dict[str, Any]]) -> List[dict[str, Any]]:
                return [m for m in metrics if m.get("metric", "").lower() in focus_metrics]

            if metrics_input and isinstance(metrics_input[0], dict):
                metrics_input = filter_metrics(metrics_input)
            elif metrics_input: # List of lists
                metrics_input = [filter_metrics(m_list) for m_list in metrics_input]
        # ----------------------------------------------------------------

        # ensure list[list]
        if metrics_input and isinstance(metrics_input[0], dict):
            metrics_lists: List[List[dict[str, Any]]] = [metrics_input]  # type: ignore[arg-type]
        else:
            metrics_lists = metrics_input  # type: ignore[assignment]

        markdown = metrics_to_markdown(metrics_lists)  # produce table

        artifact = Artifact(name="comparison", parts=[TextPart(text=markdown)])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        await self._emit_karma(self.agent_id, +2, reason="compare-ok")

        # Emit critique task with claim summarised from table (simple message)
        follow_task = Task(task_type="Critique_Claim", payload={"claim": "See comparison table"})
        await self._emit_task(follow_task)

        logger.info("%s produced comparison table", self.agent_id) 