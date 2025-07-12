"""FetcherAgent – downloads PDF given a URL or BibTeX/DOI info.

Payload expectation (MVP):
{
    "url": "https://arxiv.org/pdf/1234.5678.pdf"
}

On success it emits:
- karma +1 for itself
- new task Summarise_Paper with payload {"pdf_path": <local_path>}
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.core import Artifact, FilePart, FileContent, Message, Role, Task, TaskStatus, TextPart
from app.utils.pdf_tools import fetch_pdf

from .base import BaseAgent

logger = logging.getLogger(__name__)


class FetcherAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Fetch_Paper":
            # Ignore unexpected tasks
            return
        url: str | None = task.payload.get("url")
        if not url:
            logger.warning("Fetcher received task without url: %s", task.id)
            await self._emit_karma(self.agent_id, -1, reason="missing-url")
            return

        # --- Specialization: Use a configured User-Agent ---
        user_agent = self.config.get("user_agent", "DefaultResearchAgent/1.0")
        logger.info(f"Fetcher {self.agent_id} using User-Agent: {user_agent}")
        # In a real implementation, `fetch_pdf` would accept this user_agent
        # For now, we just log it to show the config is being used.

        try:
            pdf_path: Path = await fetch_pdf(url)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to fetch %s: %s", url, exc)
            await self._emit_karma(self.agent_id, -2, reason="download-failed")
            return

        # Build artifact referencing the local file URI (not bytes for now)
        uri_str = str(pdf_path)
        part = FilePart(type="file", file={"uri": uri_str})
        artifact = Artifact(name="paper", parts=[part])
        # Update task status to completed
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        await self._emit_karma(self.agent_id, +2, reason="fetch-success")

        # Follow-up tasks
        payload = {"pdf_path": str(pdf_path)}
        # 1. Summariser (optional full summary)
        await self._emit_task(Task(task_type="Summarise_Paper", payload=payload))
        # 2. Pre-filter for metrics extraction
        await self._emit_task(Task(task_type="Filter_Pages", payload=payload))

        logger.info("%s fetched %s -> %s", self.agent_id, url, pdf_path) 