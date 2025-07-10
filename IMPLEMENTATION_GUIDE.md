# Implementation Guide: Karma Sandbox
## Table of Contents
1. [Overview](#part-1-current-core-architecture-phase-1)
2. [Current Core Architecture](#part-1-current-core-architecture-phase-1)
3. [Planned Improvements](#part-2-planned-improvements-phase-2---a-deep-karma-economy)
4. [Developer Environment & Setup](#appendix-a-developer-environment--setup)
5. [System Diagrams](#appendix-b-system-diagrams)

This document provides a deep, technical overview of the Karma Sandbox's core architecture. It is intended for developers who wish to understand the internal mechanics of the system, from task queuing to agent execution and the flow of karma.

## Change History (Agile Iterations)
We maintain this project using an agile-like methodology, with iterative improvements based on user feedback, bug fixes, and feature enhancements. Below is a step-by-step history of major versions and changes, including code diffs where relevant. Each 'iteration' represents a cycle of planning, implementation, testing, and review.

### Iteration 0: Initial v1 (Legacy - Redis-Based)
- **Focus:** Basic mono-repo pipeline with static agent registry and Redis queue.
- **Key Components:** `STATIC_AGENT_REGISTRY` in `scheduler.py`, Redis for task queue, OpenAI for LLMs.
- **Changes:** N/A (baseline).
- **Status:** Deprecated; useful for backward compatibility via `USE_FALLBACK_REGISTRY` env var.

### Iteration 1: v2 Migration (Postgres-Backend)
- **Focus:** Replace Redis with Postgres for durability; add dynamic agent registration.
- **Key Changes:**
  - New `core/task_queue.py` and `core/agent_directory.py` for Postgres-based queue and directory.
  - Agents now register via `AgentDirectory.register()` in `base.py`.
  - Scheduler falls back to static registry if no agents registered.
  - Removed Redis from `docker-compose.yml`; added Postgres service.
  - Updated deps in `pyproject.toml`: removed `redis`; added `asyncpg`, `SQLAlchemy[asyncio]`.
- **Rationale:** Improves durability, reduces dependencies; based on user-reported Redis issues.
- **Diff Example (scheduler.py):**
  ```diff
  - # Redis logic
  + # Postgres TaskQueue
  ```
- **Status:** Current baseline.

### Iteration 2: DB Compatibility & Error Fixes
- **Focus:** Handle PgBouncer/Supabase issues (prepared statements, LISTEN/NOTIFY).
- **Key Changes:**
  - Engine config in `task_queue.py`: `statement_cache_size=0`, `poolclass=NullPool`.
  - Replaced LISTEN/NOTIFY with polling in `_notification_listener()`.
  - Split SQL execution in `create_schema` to avoid transaction mode issues.
  - Added IPv4 pooler URL support in `.env`.
- **Rationale:** User errors like 'DuplicatePreparedStatementError' on Supabase.
- **Status:** Stable for cloud DBs.

### Iteration 3: Performance Logging & Hang Fixes
- **Focus:** Debug 'hangs' in ReaderAgent; add granular logging and safeguards.
- **Key Changes:**
  - Detailed logs in `reader_agent.py`: extraction/chunking/summarization timings, peak memory via `psutil`/`resource`.
  - Fixed infinite loop in `text_split.py` chunk_text (break on end-of-text).
  - Added LLM timeouts (30s) and configurable max_chunks (env: MAX_SUMMARY_CHUNKS, default 5) to respect rate limits.
  - Cross-platform memory logging (psutil on Windows).
  - Added `psutil` to `pyproject.toml` dependencies.
- **Rationale:** User reports of 'hangs' during summarization; traced to slow LLM calls and chunking loops.
- **Diff Example (reader_agent.py):**
  ```diff
  + max_chunks = int(os.getenv("MAX_SUMMARY_CHUNKS", 5))
  + if len(chunks) > max_chunks: chunks = chunks[:max_chunks]
  ```
- **Status:** Improved debuggability; prevents API overload.

### Next Iteration (Planned)
- **User Stories:** Enhance error handling for PDF parsing; integrate profiling tools like Sciagraph.
- **Backlog:** Dynamic karma rewards, peer validation.
- **Review:** After each run, check logs for outliers (e.g., duration/token > 0.001s); profile slow chunks.

## Part 1: Current Core Architecture (Phase 1)

The current system is a mono-repository, multi-agent pipeline that runs entirely on a single machine. It is designed as a closed loop where agents are orchestrated by a central scheduler, communicating via an in-process message bus.

### 1.1. The Orchestrator (`orchestrator/orchestrator.py`)

The `OrchestratorRuntime` is the heart of the system. Its primary responsibilities are:

-   **Initialization:** It instantiates all agents defined in `AGENT_CLASSES`, giving each a unique ID and a dedicated `asyncio.Queue` to serve as its personal inbox.
-   **Dependency Injection:** It provides each agent with two critical callback functions: `emit_task` (to send new tasks back to the central queue) and `emit_karma` (to record a reputation delta in the ledger).
-   **Starting the Event Loop:** It launches all agents and the central `Scheduler` as concurrent `asyncio` tasks.

### 1.2. The Task Queue & Scheduler (`orchestrator/scheduler.py`)

The scheduler is responsible for routing tasks to the most appropriate agents.

-   **Redis as a Message Bus:** A simple Redis list (`task_queue`) is used as the central task queue. This provides a robust, non-blocking message bus that decouples the orchestrator from the agents.
-   **Static Agent Registry:** The `STATIC_AGENT_REGISTRY` dictionary maps each `task_type` (e.g., `"Summarise_Paper"`) to a list of `agent_id`s that are capable of performing that task.
-   **Karma-Aware Selection:** This is the core of the current reputation system. When a task is popped from the queue, the `Scheduler` performs the following logic:
    1.  It identifies the list of candidate agents for the given `task_type`.
    2.  It queries the `KarmaLedger` to get the current karma score for each candidate.
    3.  It sorts the candidates in descending order of their karma score.
    4.  It dispatches the task to the inbox of the highest-scoring agent.

### 1.3. The Karma Ledger (`core/karma.py`)

The `KarmaLedger` is a simple, append-only accounting system for reputation.

-   **Postgres Backend:** It uses a single table, `karma_events`, in a PostgreSQL database. The schema is managed via SQLAlchemy.
-   **Append-Only Deltas:** Agent actions do not modify a score directly. Instead, they insert a new row into the table containing the `agent_id`, the karma `delta` (e.g., `+3` or `-1`), and a `reason`.
-   **On-Demand Scoring:** An agent's total karma score is not stored. It is calculated dynamically at runtime by summing all `delta` values for a given `agent_id`. This ensures the ledger is simple and auditable.

### 1.4. Agent Lifecycle (`agents/base.py` & Implementations)

All agents inherit from `BaseAgent`.

-   **Run Loop:** Each agent runs a `run_forever` method, which is a simple `while True` loop that asynchronously waits for a `Task` to appear in its inbox queue.
-   **Task Handling:** Upon receiving a task, the agent's `_handle` method is invoked. This is where the agent's specific business logic resides (e.g., calling an LLM, parsing a file).
-   **Emitting Outputs:**
    1.  **Artifacts:** An agent attaches its work product (e.g., a summary, a list of metrics) to the `Task` object as an `Artifact`.
    2.  **Karma:** It calls the `_emit_karma` function to record its performance in the ledger.
    3.  **Follow-up Tasks:** It can create and emit a new `Task` object using `_emit_task`, which places the next task in the pipeline onto the central Redis queue for the `Scheduler` to handle.

### 1.5. Data Flow: A Complete Example (`Fetch_Paper` -> `Summarise_Paper`)

1.  **Initial Task:** `run_pipeline.py` enqueues a `Task` with `task_type="Fetch_Paper"`.
2.  **Scheduling:** The `Scheduler` pops this task, sees that `fetcher-1`, `fetcher-2`, and `fetcher-3` are candidates, checks their karma scores, and assigns the task to the one with the highest score (e.g., `fetcher-1`).
3.  **Execution (Fetcher):** `fetcher-1` receives the task, downloads the PDF, and saves it locally.
4.  **Feedback & Follow-up (Fetcher):**
    -   It calls `_emit_karma(self.agent_id, +2, "fetch-success")`. A new row is added to the `karma_events` table.
    -   It creates a new `Task` with `task_type="Summarise_Paper"` and a payload containing the path to the downloaded PDF.
    -   It calls `_emit_task` to push this new task to the central Redis queue.
5.  **Next Cycle:** The `Scheduler` now pops the `Summarise_Paper` task, and the process repeats with the `ReaderAgent`s.

---

## Part 2: Planned Improvements (Phase 2 - A Deep Karma Economy)

The long-term vision is to evolve the current system into a sophisticated, self-regulating trust economy. This involves transforming karma from a simple score into a multi-faceted asset that is earned, staked, and decays over time.

### 2.1. Phase 1: Dynamic, Performance-Based Rewards

Move beyond static karma rewards to a dynamic calculation based on the quality and efficiency of an agent's work.

-   [ ] **Implement a `ReviewerAgent`:** Create a new agent (likely using a powerful LLM like GPT-4o) whose sole purpose is to evaluate artifacts from other agents. It will produce a `quality_score` (e.g., 0.0 to 1.5).
-   [ ] **Introduce Dynamic Karma Formula:** The karma delta for a completed task will be calculated using a formula like:
    `Karma Delta = (Base Reward * Quality Score) - (Time Penalty + Resource Penalty)`
-   [ ] **Track Performance Metrics:** Instrument agents to report on execution time and resource consumption (e.g., LLM tokens used, CPU time).

### 2.2. Phase 2: Contextual Reputation & Specialization

Agents should not have a single global score. Their reputation should be contextual, allowing them to become trusted specialists in specific domains.

-   [ ] **Implement Task Tagging:** Add a `tags` field to `Task` models (e.g., `["#peft", "#summarization"]`).
-   [ ] **Scoped Karma Storage:** Modify the `karma_events` table to store karma as a JSONB object, allowing for scoped scores: `{ "global": 150, "scopes": { "#peft": 85, "#summarization": 70 } }`.
-   [ ] **Upgrade Scheduler Logic:** The scheduler must be updated to perform weighted matching based on an agent's karma in the specific tags required by a task.

### 2.3. Phase 3: Peer Validation & Karma Staking

Create a self-policing network where agents are incentivized to cooperate, validate each other's work, and take calculated risks.

-   [ ] **Implement Peer Review:** Allow an agent to emit a small karma delta (+/- 0.1) for the work of the *previous* agent in the chain (e.g., the `ReaderAgent` can downvote a `FetcherAgent` for a corrupt PDF).
-   [ ] **Introduce Karma Staking:** To accept a high-value task, require an agent to "stake" a percentage of its karma. If it succeeds, it gets the stake back plus the reward. If it fails (as judged by the `ReviewerAgent`), it forfeits the stake.

### 2.4. Phase 4: Temporal Dynamics & Economic Balance

Ensure the karma economy remains dynamic, rewarding active participation and preventing stagnation.

-   [ ] **Implement Karma Decay:** Introduce a mechanism (e.g., a periodic cron job) that slowly reduces all karma scores over time, preventing "retired" agents from hoarding reputation.
-   [ ] **Model Reputation Volatility:** A new agent's karma should change more dramatically with successes and failures than a veteran agent's. This allows new, promising agents to rise quickly while protecting established agents from being ruined by a single error.

---

## Current vs Future Karma at a Glance

| Aspect | Phase 1 (Today) | Phase 2+ (Planned Deep Karma Economy) |
|---|---|---|
| **Reward source** | Each agent calls `_emit_karma(±Δ)` with a *fixed* value baked into its code. | `ReviewerAgent` calculates a *dynamic* delta: `(base reward × quality) − (time + resources)`.
| **Score granularity** | Single global score per agent (SUM of all deltas). | Per-tag *scoped* scores (e.g., `#peft`, `#summarization`) **+** global aggregate.
| **Task selection** | Scheduler picks highest global score. | Scheduler performs weighted match on relevant tag scores, global score, and available stake.
| **Risk & validation** | None – no cost to accept a task; no peer feedback. | Agents must *stake* karma; peers can up/down-vote; failure slashes stake.
| **Time dynamics** | Score is permanent. | Karma *decays* slowly; new agents have higher volatility so they can catch up.

### Hard-coded Karma Deltas (Phase 1)

| Agent | Event/Reason | Δ Karma |
|---|---|---|
| Fetcher | `fetch-success` | **+2** |
| Fetcher | `missing-url` | **−1** |
| Fetcher | `download-failed` | **−2** |
| Reader | `summary-ok` | **+3** |
| Reader | `pdf-missing`, `empty-pdf` | **−1** |
| Metrician | `metrics-parsed` (success) | **+2** |
| Metrician | `metrics-parsed` (no metrics) | **−1** |
| Analyst | `compare-ok` | **+2** |
| Analyst | `no-metrics` | **−1** |
| Debater | `critique-done` | **+2** |
| Debater | `no-claim` | **−1** |
| Synthesiser | `report-done` | **+1** |
| *Any agent* | Uncaught exception | **−1** |

> These values live directly in the agent source files (e.g., `app/agents/fetcher_agent.py`). In Phase 2 they will be replaced by dynamic calculations provided by `ReviewerAgent`.

---

## Switching from OpenAI to OpenRouter

OpenRouter provides an OpenAI-compatible HTTP interface, so only minimal changes are required.

1. **Set the new key & base URL**

   ```bash
   # .env
   OPENROUTER_API_KEY="sk-..."
   OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
   ```

2. **Update environment wiring**

   Add a small helper (e.g., `app/core/openai_client.py`):

   ```python
   import os
   import openai

   openai.api_key = os.getenv("OPENROUTER_API_KEY")
   openai.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
   ```

3. **Import this helper in each agent that calls OpenAI** (`ReaderAgent`, `DebaterAgent`) before the first request. No other code changes are needed because the SDK methods (`openai.AsyncOpenAI()` etc.) remain the same.

4. **Optional headers**

   Some OpenRouter deployments expect a `HTTP-Referer` or `X-Title` header. If required, set:

   ```python
   openai.headers = {
       **openai.headers,
       "HTTP-Referer": "https://yourdomain.com",
       "X-Title": "Karma Sandbox"
   }
   ```

Once these steps are completed you can remove `OPENAI_API_KEY` from the environment; the system will exclusively use your OpenRouter credentials.

---

## Appendix A: Developer Environment & Setup

### A.1. Prerequisites
- Python 3.11+
- Docker (for Redis & Postgres containers)
- `uv` package manager (installed automatically in the Dockerfile, optional for local dev)

### A.2. Quick Local Run (no Docker)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # or `uv pip sync`
export OPENAI_API_KEY=sk-...
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/karma
export REDIS_URL=redis://localhost:6379/0
createdb karma   # if using local Postgres
python scripts/run_pipeline.py --url https://arxiv.org/pdf/2106.09685.pdf
```

### A.3. Docker Compose
```bash
cp .env.example .env  # fill in secrets
docker-compose up --build
```

### A.4. Running Tests
```bash
pytest -q
```

---

## Appendix B: System Diagrams

### B.1. High-Level Data Flow
```mermaid
sequenceDiagram
    participant Queue as Redis Task Queue
    participant Sched as Scheduler
    participant F as Fetcher
    participant R as Reader
    participant M as Metrician
    participant A as Analyst
    participant D as Debater
    participant Sy as Synthesiser
    Queue->>Sched: BLPOP task
    Sched-->>F: Fetch_Paper
    F-->>Queue: Summarise_Paper
    Sched-->>R: Summarise_Paper
    R-->>Queue: Extract_Metrics
    Sched-->>M: Extract_Metrics
    M-->>Queue: Compare_Methods
    Sched-->>A: Compare_Methods
    A-->>Queue: Critique_Claim
    Sched-->>D: Critique_Claim
    D-->>Queue: Synthesise_Report
    Sched-->>Sy: Synthesise_Report
    Sy-->>Queue: completed
```

### B.2. Karma Event Table (SQL)
```sql
CREATE TABLE karma_events (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(64) NOT NULL,
    delta INTEGER NOT NULL,
    reason VARCHAR(255),
    task_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---