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
from pdf2image import convert_from_path

from app.core import Artifact, Message, Part, Role, Task, TaskStatus, TextPart
from app.utils.text_split import chunk_text, count_tokens

from .base import BaseAgent

logger = logging.getLogger(__name__)

# Previously used direct OpenAI model – now replaced by OpenRouter
# MODEL = "gpt-4o-mini"

# Commented out OpenRouter configuration
# OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# MODEL = "openrouter/cypher-alpha:free"

SUMMARY_PROMPT = (
    "You are an expert ML researcher. Summarise the following paper section in 5\n"
    "bullet points capturing the main contributions, methods, and findings.\n"
)
DEFAULT_MODEL = "gpt-4o-mini-2"


async def _summarise_chunk(client: openai.AsyncClient, chunk: str, model: str, prompt: str) -> str:
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
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
        image_paths = await self._extract_images(pdf_path, task.session_id)
        extract_secs = time.perf_counter() - t0
        logger.info("[%s] Extracted text from %s (%.1fs, %d chars)", self.agent_id, pdf_path.name, extract_secs, len(text))
        if not text:
            await self._emit_karma(self.agent_id, -1, reason="empty-pdf")
            return

        # --- Specialization: Use configured prompt and model ---
        summary_prompt = self.config.get("summary_prompt", SUMMARY_PROMPT)
        summary_model = self.config.get("summary_model", DEFAULT_MODEL)
        logger.info(f"Reader {self.agent_id} using model '{summary_model}' with prompt: '{summary_prompt[:50]}...'")


        # Use Azure OpenAI GPT-4o-mini with config from .env
        client = openai.AsyncAzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version="2025-01-01-preview",
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
                summary = await asyncio.wait_for(
                    _summarise_chunk(client, chunk, model=summary_model, prompt=summary_prompt), 
                    timeout=30.0
                )
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

        # Forward summary for downstream agents
        follow_payload: dict[str, Any] = {
            "pdf_path": str(pdf_path),
            "summary": combined_summary,
            "image_paths": image_paths,
        }
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

    async def _extract_images(self, pdf_path: Path, session_id: str | None) -> List[str]:
        """Extract images from PDF using PyMuPDF (fitz) instead of pdf2image/Poppler."""
        try:
            import fitz  # PyMuPDF
            import io
            from PIL import Image
            
            # Create results directory if needed
            session_dir = Path("data/results")
            if session_id:
                session_dir = session_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            
            # Open the PDF
            doc = fitz.open(str(pdf_path))
            saved_paths = []
            
            # For each page
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                
                # Get images from the page
                image_list = page.get_images(full=True)
                
                for img_index, img_info in enumerate(image_list):
                    try:
                        xref = img_info[0]  # Get the image reference
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        
                        # Skip small images (likely icons or decorations)
                        img = Image.open(io.BytesIO(image_bytes))
                        width, height = img.size
                        if width < 100 or height < 100:
                            continue
                            
                        # Save the image
                        img_path = session_dir / f"page_{page_num+1}_img_{img_index+1}.png"
                        with open(img_path, "wb") as f:
                            f.write(image_bytes)
                        saved_paths.append(str(img_path))
                    except Exception as img_exc:
                        logger.warning(f"Failed to extract image {img_index} on page {page_num+1}: {img_exc}")
            
            logger.info("[%s] Extracted %d images from %s using PyMuPDF", self.agent_id, len(saved_paths), pdf_path.name)
            return saved_paths
            
        except ImportError:
            logger.warning("PyMuPDF (fitz) not installed, skipping image extraction")
            return []
        except Exception as e:
            logger.error(f"Image extraction failed: {str(e)}")
            return [] 