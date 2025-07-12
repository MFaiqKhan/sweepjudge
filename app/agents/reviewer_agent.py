"""
The ReviewerAgent is responsible for evaluating artifacts produced by other agents
and assigning a dynamic karma score based on quality.
"""
from __future__ import annotations

import logging
import os
import json
import time
from typing import Any, Dict, List
import asyncio
import openai

from app.core import Artifact, DataPart, Task, TaskStatus
from .base import BaseAgent

logger = logging.getLogger(__name__)

REVIEW_PROMPT_TEMPLATE = """
You are a meticulous and fair reviewer in a multi-agent AI system. Your task is to evaluate the output of another agent.
Be objective. Base your review solely on the provided artifact.

**Artifact to Review:**
```json
{artifact_json}
```

**Instructions:**
1.  **Assess Quality**: Based on the artifact, rate its quality on a scale of 0.0 to 1.5.
    - 0.0: Completely incorrect or empty.
    - 0.5: Poor quality, contains major errors.
    - 1.0: Acceptable, meets the basic requirements.
    - 1.2: High quality, clear, correct, and well-structured.
    - 1.5: Exceptional, insightful, and exceeds expectations.
2.  **Provide Justification**: Briefly explain your reasoning for the score.
3.  **Execution Time**: The task took {duration:.2f} seconds to complete. Consider this in your overall assessment (e.g., penalize for excessive slowness if applicable, but don't over-emphasize it).

**Output Format (JSON only):**
{{
  "quality_score": <float>,
  "justification": "<string>"
}}
"""

DEFAULT_BASE_REWARD = 3


class ReviewerAgent(BaseAgent):
    """An agent that reviews the work of other agents."""

    TASK_TYPES = ["Review_Artifact"]

    async def _handle(self, task: Task) -> None:
        """
        Handles a review task.
        - Calls an LLM to get a quality score.
        - Calculates dynamic karma.
        - Emits karma for the original agent.
        - Marks the original task as completed.
        """
        original_task_id = task.payload.get("original_task_id")
        original_agent_id = task.payload.get("original_agent_id")
        artifact_to_review = task.payload.get("artifact")
        duration = task.payload.get("duration", 0.0)

        if not all([original_task_id, original_agent_id, artifact_to_review]):
            await self._emit_karma(self.agent_id, -2, "invalid_review_request")
            logger.error("Reviewer received task with missing payload fields.")
            # We cannot mark the original task as failed without its ID, so we just fail this one.
            task.status = TaskStatus.failed
            return

        # --- Specialization: Use configured prompt and karma logic ---
        prompt_template = self.config.get("evaluation_prompt_template", REVIEW_PROMPT_TEMPLATE)
        base_reward = self.config.get("base_reward", DEFAULT_BASE_REWARD)
        logger.info(f"Reviewer {self.agent_id} using base_reward={base_reward}.")
        
        # 1. Get review from LLM
        review_json = await self._get_llm_review(artifact_to_review, duration, prompt_template)
        if not review_json:
            # If review fails, we can't score the original task.
            # Mark the original task as failed so it can be retried.
            logger.error(f"LLM review failed for artifact of task {original_task_id}.")
            await self._mark_failed(original_task_id, original_agent_id)
            task.status = TaskStatus.failed
            return

        quality_score = review_json.get("quality_score", 0.0)
        justification = review_json.get("justification", "Review failed.")

        # 2. Calculate Dynamic Karma
        # Base reward is scaled by quality, using the configured base_reward
        karma_delta = int(base_reward * quality_score)
        
        # Add a small penalty for long execution times
        if duration > 60: # e.g., over 1 minute
            karma_delta -= 1

        # 3. Emit Karma for the original agent
        review_reason = f"Reviewer score: {quality_score:.2f}. {justification}"
        await self._emit_karma(original_agent_id, karma_delta, review_reason)
        logger.info(f"Awarded {karma_delta} karma to {original_agent_id} for task {original_task_id}.")

        # 4. Mark the original task as completed
        await self._mark_completed(original_task_id, original_agent_id)
        logger.info(f"Marked original task {original_task_id} as completed.")

        # 5. Complete this review task
        task.status = TaskStatus.completed
        review_artifact = Artifact(name="review", parts=[DataPart(data=review_json)])
        task.artifacts = [review_artifact]

    async def _get_llm_review(self, artifact: Dict[str, Any], duration: float, prompt_template: str) -> Dict[str, Any] | None:
        """Calls the LLM to get a quality score for an artifact."""
        try:
            client = openai.AsyncAzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version="2025-01-01-preview",
            )
            
            prompt = prompt_template.format(
                artifact_json=json.dumps(artifact, indent=2),
                duration=duration,
            )

            response = await client.chat.completions.create(
                model="gpt-4o-mini-2",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            
            response_text = response.choices[0].message.content
            return json.loads(response_text)
            
        except Exception as e:
            logger.exception(f"Error getting LLM review: {e}")
            return None 