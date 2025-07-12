"""DebaterAgent – generates pro/cons for a given claim.

Input payload: {"claim": str}
Output: JSON with lists of pros, cons; karma; triggers Synthesise_Report.

The agent internally spawns two calls to the LLM with different system
prompts (optimist vs skeptic) then merges outputs.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import asyncio
import openai

from app.core import Artifact, DataPart, Task, TaskStatus

from .base import BaseAgent

logger = logging.getLogger(__name__)

# Commented out OpenRouter configuration
# OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# MODEL = "openrouter/cypher-alpha:free"

SYSTEM_OPTIMIST = (
    "You are an enthusiastic but rigorous peer reviewer. Provide arguments that SUPPORT the claim."  # noqa: E501
)
SYSTEM_SKEPTIC = (
    "You are a critical peer reviewer. Provide arguments that CHALLENGE the claim."  # noqa: E501
)


async def _review(client: openai.AsyncClient, system_prompt: str, claim: str) -> List[str]:
    resp = await client.chat.completions.create(
        model="gpt-4o-mini-2",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Claim: {claim}\nGive bullet points."},
        ],
        max_tokens=256,
        temperature=0.4,
    )
    text = resp.choices[0].message.content.strip()
    bullets = [line.lstrip("-• ").strip() for line in text.split("\n") if line.strip()]
    return bullets


class DebaterAgent(BaseAgent):
    async def _handle(self, task: Task) -> None:  # noqa: D401
        if task.task_type != "Critique_Claim":
            return
        claim: str | None = task.payload.get("claim")
        if not claim:
            await self._emit_karma(self.agent_id, -1, reason="no-claim")
            return

        # Use Azure OpenAI GPT-4o-mini with config from .env
        client = openai.AsyncAzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version="2025-01-01-preview",
        )

        # --- Specialization: Use a configured debate strategy ---
        strategy = self.config.get("debate_strategy", "balanced")
        logger.info(f"Debater {self.agent_id} using strategy: {strategy}")

        pros, cons = await self._generate_pro_con(client, claim, strategy)
        critique = {"pros": pros, "cons": cons, "claim": claim}

        part = DataPart(data=critique)  # type: ignore[arg-type]
        artifact = Artifact(name="critique", parts=[part])
        task.status = TaskStatus.completed
        task.artifacts = [artifact]

        await self._emit_karma(self.agent_id, +2, reason="critique-done")

        # Final synthesis stage
        follow_task = Task(task_type="Synthesise_Report", payload={})
        await self._emit_task(follow_task)

        logger.info("%s critiqued claim", self.agent_id)

    async def _generate_pro_con(
        self, client: openai.AsyncClient, claim: str, strategy: str
    ) -> tuple[List[str], List[str]]:
        
        pro_task = None
        if strategy in ("balanced", "optimist_only"):
            pro_task = _review(client, SYSTEM_OPTIMIST, claim)

        con_task = None
        if strategy in ("balanced", "skeptic_only"):
            con_task = _review(client, SYSTEM_SKEPTIC, claim)

        tasks = [t for t in (pro_task, con_task) if t is not None]
        results = await asyncio.gather(*tasks)

        pros, cons = [], []
        result_idx = 0
        if pro_task:
            pros = results[result_idx]
            result_idx += 1
        if con_task:
            cons = results[result_idx]

        return pros, cons 