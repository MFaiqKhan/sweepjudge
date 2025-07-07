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

import openai

from app.core import Artifact, DataPart, Task, TaskStatus

from .base import BaseAgent

logger = logging.getLogger(__name__)

# OpenRouter configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openrouter/cypher-alpha:free"

SYSTEM_OPTIMIST = (
    "You are an enthusiastic but rigorous peer reviewer. Provide arguments that SUPPORT the claim."  # noqa: E501
)
SYSTEM_SKEPTIC = (
    "You are a critical peer reviewer. Provide arguments that CHALLENGE the claim."  # noqa: E501
)


async def _review(client: openai.AsyncClient, system_prompt: str, claim: str) -> List[str]:
    resp = await client.chat.completions.create(
        model=MODEL,
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

        client = openai.AsyncOpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=OPENROUTER_BASE_URL,
        )
        pros, cons = await self._generate_pro_con(client, claim)
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
        self, client: openai.AsyncClient, claim: str
    ) -> tuple[List[str], List[str]]:
        pros, cons = await openai.aiosession.gather(  # type: ignore[attr-defined]
            _review(client, SYSTEM_OPTIMIST, claim),
            _review(client, SYSTEM_SKEPTIC, claim),
        )
        return pros, cons 