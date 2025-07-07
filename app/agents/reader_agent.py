"""ReaderAgent – summarises a PDF into key points.

Input payload:
{
    "pdf_path": "/abs/path/file.pdf"
}

Emits karma, Extract_Metrics task, and stores summary as artifact.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List

import openai
import PyPDF2

from app.core import Artifact, Message, Part, Role, Task, TaskStatus, TextPart
from app.utils.text_split import chunk_text

from .base import BaseAgent

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

SUMMARY_PROMPT = (
    "You are an expert ML researcher. Summarise the following paper section in 5\n"
    "bullet points capturing the main contributions, methods, and findings.\n"
)


async def _summarise_chunk(client: openai.AsyncClient, chunk: str) -> str:
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": chunk},
        ],
        max_tokens=256,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


class ReaderAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Summarise_Paper":
            return
        pdf_path_str: str | None = task.payload.get("pdf_path")
        if not pdf_path_str or not Path(pdf_path_str).exists():
            await self._emit_karma(self.agent_id, -1, reason="pdf-missing")
            return

        pdf_path = Path(pdf_path_str)
        text = self._extract_text(pdf_path)
        if not text:
            await self._emit_karma(self.agent_id, -1, reason="empty-pdf")
            return

        client = openai.AsyncOpenAI()
        summaries: List[str] = []
        for chunk in chunk_text(text):
            try:
                summaries.append(await _summarise_chunk(client, chunk))
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Summary chunk failed: %s", exc)
                continue

        combined_summary = "\n".join(summaries)

        # Store artifact
        part: Part = TextPart(text=combined_summary)
        artifact = Artifact(name="summary", parts=[part])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        await self._emit_karma(self.agent_id, +3, reason="summary-ok")

        # Emit next task – metrics extraction
        follow_payload: dict[str, Any] = {"pdf_path": str(pdf_path)}
        follow_task = Task(task_type="Extract_Metrics", payload=follow_payload)
        await self._emit_task(follow_task)

        logger.info("%s summarised %s", self.agent_id, pdf_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_text(self, pdf_path: Path) -> str:
        try:
            reader = PyPDF2.PdfReader(str(pdf_path))
            texts = [p.extract_text() or "" for p in reader.pages]
            return "\n".join(texts)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to extract text: %s", exc)
            return "" 