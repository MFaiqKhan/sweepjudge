"""SynthesiserAgent – compiles final markdown report.

MVP strategy: payload may include pointers or simply rely on earlier artifacts
stored elsewhere. For now, it creates a placeholder report linking to artifacts.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.core import Artifact, Task, TaskStatus, TextPart

from .base import BaseAgent

logger = logging.getLogger(__name__)


class SynthesiserAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Synthesise_Report":
            return

        timestamp = dt.datetime.utcnow().isoformat()
        report_md = (
            f"# PEFT Research Report\n\nGenerated: {timestamp}\n\n"
            "(This is a placeholder synthesis in the MVP.)\n\n"
            "Earlier artifacts (summary, metrics table, critique) are available in the task log.\n"
        )

        artifact = Artifact(name="report", parts=[TextPart(text=report_md)])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        await self._emit_karma(self.agent_id, +1, reason="report-done")

        logger.info("%s produced final report", self.agent_id) 