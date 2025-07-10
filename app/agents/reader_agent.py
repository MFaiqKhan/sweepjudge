"""ReaderAgent – summarises a PDF into key points.

Input payload:
{
    "pdf_path": "/abs/path/file.pdf"
}

Emits karma, Extract_Metrics task, and stores summary as artifact.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List
import sys
import asyncio
if sys.platform == "win32":
    from psutil import Process
else:
    from resource import getrusage, RUSAGE_SELF
import time

import openai
import PyPDF2

from app.core import Artifact, Message, Part, Role, Task, TaskStatus, TextPart
from app.utils.text_split import chunk_text, count_tokens

from .base import BaseAgent

logger = logging.getLogger(__name__)

# Previously used direct OpenAI model – now replaced by OpenRouter
# MODEL = "gpt-4o-mini"

# OpenRouter configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openrouter/cypher-alpha:free"

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
        # ------------------------------- PDF → Text -------------------------------
        t0 = time.perf_counter()
        text = self._extract_text(pdf_path)
        extract_secs = time.perf_counter() - t0
        logger.info("[%s] Extracted text from %s (%.1fs, %d chars)", self.agent_id, pdf_path.name, extract_secs, len(text))
        if not text:
            await self._emit_karma(self.agent_id, -1, reason="empty-pdf")
            return

        client = openai.AsyncOpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=OPENROUTER_BASE_URL,
        )
        # --------------------------- Text → Chunks ---------------------------
        t1 = time.perf_counter()
        chunks = chunk_text(text)
        # Cap at configurable max chunks to avoid rate limits (env: MAX_SUMMARY_CHUNKS)
        max_chunks = int(os.getenv("MAX_SUMMARY_CHUNKS", 5))
        if len(chunks) > max_chunks:
            logger.warning("[%s] Truncating to first %d chunks (original: %d) to respect API limits",
                           self.agent_id, max_chunks, len(chunks))
            chunks = chunks[:max_chunks]
        chunk_secs = time.perf_counter() - t1
        total_chunks = len(chunks)
        # Update total_tokens after possible truncation
        total_tokens = sum(count_tokens(c) for c in chunks)
        logger.info("[%s] Split into %d chunks (%d tokens) in %.1fs", self.agent_id, total_chunks, total_tokens, chunk_secs)

        summaries: List[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            token_len = count_tokens(chunk)
            logger.info("[%s] Summarising chunk %d/%d (%d tokens)", self.agent_id, idx, total_chunks, token_len)

            start_time = time.perf_counter()
            try:
                # Timeout after 30s to prevent indefinite hangs on slow LLM responses
                summary = await asyncio.wait_for(_summarise_chunk(client, chunk), timeout=30.0)
                duration = time.perf_counter() - start_time
                logger.info("[%s] Chunk %d summarised in %.1fs (%d tokens) ", self.agent_id, idx, duration, token_len)
                summaries.append(summary)
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("[%s] Summary of chunk %d failed: %s", self.agent_id, idx, exc)
                continue

        combined_summary = "\n".join(summaries)

        # Log peak memory and simple performance model (duration per token)
        if sys.platform == "win32":
            peak_mem_kb = Process().memory_info().peak_wset // 1024  # Peak working set in KB
        else:
            peak_mem_kb = getrusage(RUSAGE_SELF).ru_maxrss
        total_duration = time.perf_counter() - t0  # From extraction start
        duration_per_token = total_duration / (total_tokens + 1e-6)  # Avoid div-by-zero
        logger.info("[%s] Summary complete: peak memory %d KB, total duration %.1fs, duration/token %.6f",
                    self.agent_id, peak_mem_kb, total_duration, duration_per_token)

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