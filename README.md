# Karma-Based Alignment Sandbox – MVP (Plan B)

## 1  Project Goal
A minimal yet functional multi-agent research assistant that showcases emergent cooperation and reputation-driven task allocation. The MVP focuses on a single research theme (Parameter-Efficient Fine-Tuning, **PEFT**) and runs entirely on one machine using an **internal JSON-RPC message schema modelled after Google's A2A protocol**.

## 2  Tech Stack
| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.11** | Async-friendly, rich LLM tooling |
| LLM API | **OpenAI (gpt-4o-mini)** for reasoning agents.<br>**Tiny Llama 1.1B** via [`vllm`](https://github.com/vllm-project/vllm) for reviewer agents | Keeps GPU/RAM footprint low |
| Web framework | **FastAPI + Uvicorn** | Async, swagger docs out-of-the-box |
| Async runtime | **asyncio** | Built-in; works with FastAPI |
| Messaging | **Redis** pub/sub | In-process JSON-RPC over channels |
| Persistence | **Postgres**: karma ledger & provenance<br>**Qdrant**: vector store for PDF embeddings | Reliable ACID + RAG |
| Containers | **Docker + docker-compose** | Reproducible dev env |
| Diagrams | **Mermaid** (rendered by GitHub) | Architecture docs |

## 3  Agents & Responsibilities
| # | Role          | Instances | Task Types         | Key Tools |
|---|---------------|-----------|--------------------|-----------|
| 1 | **Fetcher**   | 3         | `Fetch_Paper`      | `pdf_tools.fetch()` |
| 2 | **Reader**    | 3         | `Summarise_Paper`  | OpenAI LLM + PDF parser |
| 3 | **Metrician** | 2         | `Extract_Metrics`  | Regex + pandas |
| 4 | **Analyst**   | 2         | `Compare_Methods`  | NumPy/pandas + LLM |
| 5 | **Debater**   | 2 personas (optimist + skeptic) in 1 container | `Critique_Claim`   | OpenAI LLM |
| 6 | **Synthesiser** | 1       | `Synthesise_Report` | OpenAI LLM + Templater |
| **Total** | **12 micro-agents** |

## 4  System-wide Message Schema (internal JSON-RPC)
```jsonc
{
  "id": "task-uuid",          // correlates everything
  "task_type": "Summarise_Paper",
  "payload": { /* task-specific */ },
  "session_id": "research-123", // optional chain grouping
  "metadata": {}
}
```
Responses carry:
```jsonc
{
  "id": "task-uuid",
  "status": "working | completed | failed | input-required",
  "artifacts": [ /* list of messages/parts */ ],
  "karma_delta": +3
}
```

## 5  Directory Layout (MVP)
```text
findmyrecruitment/
├─ app/
│  ├─ orchestrator/
│  │   ├─ orchestrator.py      # queue & scheduler
│  │   └─ scheduler.py         # karma-aware selection logic
│  ├─ agents/
│  │   ├─ __init__.py
│  │   ├─ base.py              # AgentBase w/ run(), review(), JSON-RPC helpers
│  │   ├─ fetcher_agent.py
│  │   ├─ reader_agent.py
│  │   ├─ metrician_agent.py
│  │   ├─ analyst_agent.py
│  │   ├─ debater_agent.py
│  │   └─ synthesiser_agent.py
│  ├─ core/
│  │   ├─ karma.py             # Ledger class, Postgres driver
│  │   ├─ models.py            # Pydantic schemas mirroring A2A
│  │   ├─ storage.py           # Qdrant / PDF cache helpers
│  │   └─ settings.py          # env vars, paths
│  └─ utils/
│     ├─ pdf_tools.py
│     └─ rag_client.py
├─ data/
│  └─ corpus/                  # pilot PDFs
├─ scripts/
│  ├─ populate_corpus.py
│  └─ start_dev.sh
├─ tests/
│  └─ test_extract_metrics.py
├─ docker-compose.yml
├─ requirements.txt
└─ README.md
```

## 6  High-Level Application Flow
```mermaid
flowchart TD
  U[User CLI / HTTP] --> ORCH[Orchestrator]
  subgraph "Micro-Agent Swarm"
    F1[Fetcher 1] F2[Fetcher 2] F3[Fetcher 3]
    R1[Reader 1] R2[Reader 2] R3[Reader 3]
    M1[Metrician 1] M2[Metrician 2]
    A1[Analyst 1] A2[Analyst 2]
    D[Debater (2 personas)]
    S[Synthesiser]
  end
  ORCH -->|task queue| F1 & F2 & F3 & R1 & R2 & R3 & M1 & M2 & A1 & A2 & D
  F1 & F2 & F3 --> ORCH
  R1 & R2 & R3 --> ORCH
  M1 & M2 --> ORCH
  A1 & A2 --> ORCH
  D --> ORCH
  ORCH --> S
  S --> ORCH --> U
```

### 6.1  Detailed Agent Sequence (example: `Summarise_Paper`)
```mermaid
sequenceDiagram
  participant O as Orchestrator
  participant R2 as ReaderAgent#2
  participant Rv as ReviewerAgent
  O->>R2: JSON-RPC {task_type: Summarise_Paper, pdf_path}
  R2-->>O: working
  R2->>LLM: prompt(pdf excerpt)
  R2-->>O: completed + artifacts[]
  O->>Rv: Review request
  Rv-->>O: score=4
  O->>KarmaDB: ΔKarma = +1.5
  O->>Queue: enqueue Extract_Metrics
```

## 7  Run Locally (dev)
```bash
# 1 clone repo
$ git clone https://github.com/yourname/karma-sandbox
$ cd karma-sandbox
# 2 install uv once (if not installed)
$ curl -LsSf https://astral.sh/uv/install.sh | sh
# 3 create virtual env & install deps
$ uv venv && uv pip sync
# 4 add your secrets
$ cp .env.example .env && edit .env
# 5 launch pipeline + enqueue default PDF
$ python scripts/start_dev.py --url https://arxiv.org/pdf/2106.09685.pdf
```

### Run via Docker
```bash
$ cp .env.example .env  # fill keys
$ docker-compose up --build
```

## 8  Key Tools / Libraries
* **LangChain** – prompt templates & PDF loaders
* **PyPDF2** – PDF text extraction
* **tiktoken** – token counting for budgeting
* **pandas / NumPy** – table wrangling
* **pytest** – unit tests

## 9  Milestone Checklist
- [x] JSON-RPC dataclasses & validation
- [x] Karma ledger with Postgres
- [ ] Fetcher & Reader agents
- [ ] Metrician + table extractor
- [ ] Karma-aware scheduler
- [ ] Synthesiser producing Markdown report
- [ ] CLI demo script

## 10  Next Steps
1. Implement remaining agents & peer-review loop.
2. Add web dashboard (FastAPI + React) for live karma visualisation.
3. Wrap agents with thin HTTP adapters → become A2A-ready.
4. Introduce Docker layer caching & resource quotas per agent.

## 11  Future Vision: A Deep Karma Economy

The current karma system is a simple reputation leaderboard. The long-term vision is to evolve it into a sophisticated, self-regulating trust economy that drives emergent, intelligent behavior without a complex reinforcement learning loop. This involves transforming karma from a simple score into a multi-faceted asset that is earned, staked, and decays over time.

### 11.1  Phase 1: Dynamic, Performance-Based Rewards

Move beyond static karma rewards (`+3` for a summary) to a dynamic calculation based on the quality and efficiency of an agent's work.

-   [ ] **Implement a `ReviewerAgent`:** Create a new agent (likely using a powerful LLM like GPT-4o) whose sole purpose is to evaluate artifacts from other agents. It will produce a `quality_score` (e.g., 0.0 to 1.5).
-   [ ] **Introduce Dynamic Karma Formula:** The karma delta for a completed task will be calculated using a formula like:
    `Karma Delta = (Base Reward * Quality Score) - (Time Penalty + Resource Penalty)`
-   [ ] **Track Performance Metrics:** Instrument agents to report on execution time and resource consumption (e.g., LLM tokens used, CPU time).

### 11.2  Phase 2: Contextual Reputation & Specialization

Agents should not have a single global score. Their reputation should be contextual, allowing them to become trusted specialists in specific domains.

-   [ ] **Implement Task Tagging:** Add a `tags` field to `Task` models (e.g., `["#peft", "#summarization"]`).
-   [ ] **Scoped Karma Storage:** Modify the `karma_events` table to store karma as a JSONB object, allowing for scoped scores: `{ "global": 150, "scopes": { "#peft": 85, "#summarization": 70 } }`.
-   [ ] **Upgrade Scheduler Logic:** The scheduler must be updated to perform weighted matching based on an agent's karma in the specific tags required by a task.

### 11.3  Phase 3: Peer Validation & Karma Staking

Create a self-policing network where agents are incentivized to cooperate, validate each other's work, and take calculated risks.

-   [ ] **Implement Peer Review:** Allow an agent to emit a small karma delta (+/- 0.1) for the work of the *previous* agent in the chain (e.g., the `ReaderAgent` can downvote a `FetcherAgent` for a corrupt PDF).
-   [ ] **Introduce Karma Staking:** To accept a high-value task, require an agent to "stake" a percentage of its karma. If it succeeds, it gets the stake back plus the reward. If it fails (as judged by the `ReviewerAgent`), it forfeits the stake.

### 11.4  Phase 4: Temporal Dynamics & Economic Balance

Ensure the karma economy remains dynamic, rewarding active participation and preventing stagnation.

-   [ ] **Implement Karma Decay:** Introduce a mechanism (e.g., a periodic cron job) that slowly reduces all karma scores over time, preventing "retired" agents from hoarding reputation.
-   [ ] **Model Reputation Volatility:** A new agent's karma should change more dramatically with successes and failures than a veteran agent's. This allows new, promising agents to rise quickly while protecting established agents from being ruined by a single error.


-----------------|||||||||------------------
Layman Terms : 

Current karma (today):  
• Every time an agent finishes a task it directly calls “add karma( ±Δ )” with a hard-coded value (e.g., +3 for a good summary, –1 for an error).  
• Those deltas are appended as rows in one Postgres table.  
• An agent’s reputation score is simply SUM( delta ).  
• When the scheduler must pick a worker, it just chooses the candidate with the largest sum.  
In short: one global score, fixed rewards, no penalties for slowness or waste, no specialization, no decay, no peer feedback—just a straightforward leaderboard.

Next-planned karma (deep economy):  
• Dynamic rewards: Δ = (Base reward × quality score) – (time & resource penalties). A ReviewerAgent supplies the quality score.  
• Scoped reputation: agents hold separate karma balances per topic or skill tag (e.g., “#peft”, “#summarization”) in addition to their global total. Scheduler matches tasks to the highest karma in the relevant scope, not just the overall leader.  
• Peer review & staking: agents can up-/down-vote the previous agent’s output and must stake a portion of their own karma before accepting high-value tasks; failure burns the stake.  
• Temporal dynamics: karma decays slowly every day, and scores for new agents change more dramatically (high volatility) so newcomers can rise fast.  
Together these additions turn the leaderboard into a living trust economy where quality, efficiency, specialization, community validation, and continued participation all shape which agent gets the next job.

© 2025 Karma Sandbox | MIT License 