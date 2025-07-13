"""AnalystAgent – compares methods across metric lists.

Input payload expects 'metrics' key with list of metrics for one paper OR list of lists.
If multiple lists provided, builds combo table; else single list table.
Outputs markdown artifact and emits Critique_Claim task.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List

import openai

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

        # Use LLM to generate real claims from metrics table
        try:
            client = openai.AsyncAzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version="2025-01-01-preview",
            )
            
            prompt = f"""
            Based on the following metrics table, generate 2-3 key claims about the research findings.
            Each claim should be a specific, verifiable statement about performance or methodology.
            Format as bullet points.
            
            {markdown}
            """
            
            resp = await client.chat.completions.create(
                model="gpt-4o-mini-2",
                messages=[
                    {"role": "system", "content": "You are an analyst. Extract key claims from research metrics."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=150,
                temperature=0.5,
            )
            
            claims_text = resp.choices[0].message.content.strip()
            # Process bullet points into a clean list
            claims = [line.lstrip("-• ").strip() for line in claims_text.split("\n") if line.strip()]
            logger.info(f"Generated {len(claims)} claims from metrics")
        except Exception as exc:
            logger.exception("Failed to generate claims with LLM: %s", exc)
            # Fallback to basic claims if LLM fails
            claims = ["The paper demonstrates improvements over baseline methods on key metrics."]

        follow_payload: dict[str, Any] = {
            "claims": claims,
            "comparison": markdown,
        }
        if "summary" in task.payload:
            follow_payload["summary"] = task.payload["summary"]
        if "metrics" in task.payload:
            follow_payload["metrics"] = task.payload["metrics"]
        if "pdf_path" in task.payload:
            follow_payload["pdf_path"] = task.payload["pdf_path"]

        follow_task = Task(
            task_type="Critique_Claim",
            payload=follow_payload,
            session_id=task.session_id,
        )
        await self._emit_task(follow_task)

        logger.info("%s produced comparison table and %d claims", self.agent_id, len(claims)) 