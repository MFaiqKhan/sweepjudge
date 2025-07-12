"""Main orchestrator script.

Runs all agents in-process, connects them via async queues, and uses the
Postgres-backed Scheduler to assign tasks.
This version includes a dynamic management API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from uvicorn import Config, Server

from app.core import Task
from app.core.agent_directory import AgentDirectory
from app.core.karma import KarmaLedger
from app.core.task_queue import TaskQueue
from app.orchestrator.scheduler import Scheduler

from app.agents.base import BaseAgent
from app.agents.fetcher_agent import FetcherAgent
from app.agents.reader_agent import ReaderAgent
from app.agents.metrician_agent import MetricianAgent
from app.agents.analyst_agent import AnalystAgent
from app.agents.debater_agent import DebaterAgent
from app.agents.synthesiser_agent import SynthesiserAgent
from app.agents.reviewer_agent import ReviewerAgent
from app.agents.prefilter_agent import PreFilterAgent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Map agent class names to their actual classes for dynamic instantiation
AGENT_CLASS_MAP = {
    "FetcherAgent": FetcherAgent,
    "ReaderAgent": ReaderAgent,
    "MetricianAgent": MetricianAgent,
    "AnalystAgent": AnalystAgent,
    "DebaterAgent": DebaterAgent,
    "SynthesiserAgent": SynthesiserAgent,
    "ReviewerAgent": ReviewerAgent,
    "PreFilterAgent": PreFilterAgent,
}


class AddAgentRequest(BaseModel):
    agent_class_name: str
    agent_id: str
    config: Optional[Dict[str, Any]] = None

class OrchestratorRuntime:
    def __init__(self) -> None:
        # Create service components from environment
        self._ledger = KarmaLedger.from_env()
        self._agent_directory = AgentDirectory.from_env()
        self._task_queue = TaskQueue.from_env()
        
        # In-memory stores for dynamic agent management
        self._agent_inboxes: Dict[str, asyncio.Queue[Task]] = {}
        self._agents: Dict[str, BaseAgent] = {}
        self._agent_tasks: Dict[str, asyncio.Task] = {}
        
        self._scheduler: Scheduler | None = None
        
        # FastAPI app for management API
        self._api_app = FastAPI(title="Agent Orchestrator API")
        self._setup_api_routes()

    def _setup_api_routes(self):
        @self._api_app.post("/agents/add", status_code=202)
        async def add_agent(request: AddAgentRequest):
            """Create and start a new agent instance."""
            try:
                await self.spawn_agent(request.agent_class_name, request.agent_id, request.config)
                return {"status": "success", "message": f"Agent {request.agent_id} is being created."}
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Agent class '{request.agent_class_name}' not found.")
            except ValueError as e:
                raise HTTPException(status_code=409, detail=str(e))

        @self._api_app.delete("/agents/remove/{agent_id}", status_code=202)
        async def remove_agent(agent_id: str):
            """Stop and remove an agent instance."""
            try:
                await self.stop_agent(agent_id)
                return {"status": "success", "message": f"Agent {agent_id} is being stopped."}
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

        @self._api_app.get("/agents/")
        async def list_agents():
            """List all currently running agents and their status."""
            if not self._agents:
                return {"agents": []}
                
            return {
                "agents": [
                    {
                        "agent_id": aid,
                        "class": ag.__class__.__name__,
                        "status": "finished" if self._agent_tasks[aid].done() else "running",
                    }
                    for aid, ag in self._agents.items()
                ]
            }

    async def spawn_agent(self, agent_class_name: str, agent_id: str, config: Optional[Dict[str, Any]] = None):
        if agent_id in self._agents:
            raise ValueError(f"Agent with id '{agent_id}' already exists.")

        agent_cls = AGENT_CLASS_MAP.get(agent_class_name)
        if not agent_cls:
            raise KeyError(f"Agent class '{agent_class_name}' not found.")

        logger.info(f"Dynamically spawning agent '{agent_id}' of class '{agent_class_name}' with config: {config}")

        inbox = asyncio.Queue()
        agent = agent_cls(
            agent_id=agent_id,
            inbox=inbox,
            emit_task=self.enqueue_task,
            emit_karma=self.add_karma,
            mark_completed=self.mark_task_completed,
            mark_failed=self.mark_task_failed,
            agent_directory=self._agent_directory,
            task_queue=self._task_queue, # Pass the task queue instance
            config=config,
        )
        
        self._agent_inboxes[agent_id] = inbox
        self._agents[agent_id] = agent
        
        task = asyncio.create_task(agent.run_forever())
        self._agent_tasks[agent_id] = task
        
    async def stop_agent(self, agent_id: str):
        if agent_id not in self._agent_tasks:
            raise KeyError(f"Agent '{agent_id}' not found.")
            
        logger.info(f"Stopping agent '{agent_id}'")
        
        task = self._agent_tasks[agent_id]
        task.cancel()
        
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"Agent {agent_id} did not terminate gracefully within 5 seconds.")
        except asyncio.CancelledError:
            pass  # Expected
            
        del self._agent_tasks[agent_id]
        del self._agents[agent_id]
        del self._agent_inboxes[agent_id]
        
    # ------------------------------------------------------------------
    # Hooks passed to agents (no changes needed here)
    # ------------------------------------------------------------------

    async def enqueue_task(self, task: Task) -> None:
        await self._task_queue.push(task)

    async def add_karma(self, agent_id: str, delta: int, reason: str | None = None) -> None:
        await self._ledger.add_delta(agent_id, delta, reason=reason)

    async def mark_task_completed(self, task_id: uuid.UUID, agent_id: str) -> None:
        await self._task_queue.mark_completed(task_id, agent_id)

    async def mark_task_failed(self, task_id: uuid.UUID, agent_id: str) -> None:
        await self._task_queue.mark_failed(task_id, agent_id)

    # ------------------------------------------------------------------
    # Send fn for scheduler -> agent inbox
    # ------------------------------------------------------------------

    async def _send_to_agent(self, agent_id: str, task: Task):
        inbox = self._agent_inboxes.get(agent_id)
        if inbox is None:
            logger.warning(f"Scheduler selected unknown or stopped agent '{agent_id}'. Re-queueing task.")
            await self.enqueue_task(task)
            return
        await inbox.put(task)

    # ------------------------------------------------------------------
    async def start(self):
        """Initialize services and start all components."""
        # Create all needed database tables
        await self._ledger.create_schema()
        await self._agent_directory.create_schema()
        await self._task_queue.create_schema()
        
        self._scheduler = Scheduler(
            karma=self._ledger,
            queue=self._task_queue,
            agent_directory=self._agent_directory,
            send_fn=self._send_to_agent,
        )
        
        await self._task_queue.initialize()

        # Launch scheduler as a background task
        scheduler_task = asyncio.create_task(self._scheduler.run_forever())

        # Launch API server
        config = Config(app=self._api_app, host="0.0.0.0", port=8000, log_level="info")
        server = Server(config)
        
        logger.info("Orchestrator runtime started. Management API at http://0.0.0.0:8000")
        
        # Concurrently run the scheduler and the API server
        await asyncio.gather(scheduler_task, server.serve())


async def main():
    runtime = OrchestratorRuntime()
    await runtime.start()


if __name__ == "__main__":
    asyncio.run(main()) 