# Karma-Sandbox: A Dynamic, Self-Optimising Multi-Agent Research Platform

This project is a multi-agent system designed for automated research, specifically for fetching, analyzing, and reporting on academic papers. It uses a karma-based reward system to encourage high-quality, efficient work from its agents, and features a dynamic architecture that allows for runtime management and specialization of the agent swarm.

## Core Concepts

1.  **Multi-Agent Pipeline**: The system is composed of several single-purpose agents that hand tasks to one another. A typical workflow involves fetching a paper, summarizing it, extracting key metrics, debating claims, and synthesizing a final report.
2.  **Karma-Based Scheduling**: Agents are rewarded or penalized with "karma" based on their performance. The central `Scheduler` uses these karma scores to decide which agent is most suitable for the next task, creating a self-optimizing feedback loop.
3.  **Dynamic Review & Reward**: After an agent completes its work, its output artifact is sent to a specialized `ReviewerAgent`. This agent uses an LLM to assess the quality of the work and assigns a dynamic karma score, ensuring that rewards are based on quality, not just completion.
4.  **Agent Specialization**: Agents are not one-size-fits-all. They can be configured at runtime with different "personalities" or capabilities. For example, you can spawn a `DebaterAgent` configured to be highly skeptical or a `MetricianAgent` that only looks for specific metrics.
5.  **Token-Efficient PDF Filtering**: To minimize expensive LLM calls, a `PreFilterAgent` uses fast heuristics (keywords, regex, table detection) to identify the most relevant pages of a long PDF, sending only a small, targeted text snippet to the metrics extractor.
6.  **Multi-Modal Analysis**: The system can now extract and analyze images from research papers, providing visual context alongside textual analysis in the final report.
7.  **Intelligent Claim Generation**: The `AnalystAgent` uses LLM to generate meaningful claims from metrics data, which are then critiqued by the `DebaterAgent` to provide balanced analysis.
8.  **Consistent Session Tracking**: All tasks within a workflow are tracked with a common session ID, ensuring artifacts are properly grouped and accessible to downstream agents.

## System Architecture

The diagram below illustrates the flow of information and tasks between the core components of the system.

```mermaid
graph TD
    subgraph "User Interaction"
        CLI_Seed[fa:fa-terminal scripts/seed_task.py]
        CLI_Manage[fa:fa-terminal scripts/manage_swarm.py]
    end

    subgraph "Orchestration Layer (FastAPI)"
        Orchestrator[fa:fa-server Orchestrator]
        Scheduler[fa:fa-calendar-alt Scheduler]
    end

    subgraph "State Management (PostgreSQL)"
        TaskQueue[fa:fa-database Task Queue]
        AgentDirectory[fa:fa-address-book Agent Directory]
        KarmaLedger[fa:fa-star Karma Ledger]
    end

    subgraph "Agent Swarm"
        Fetcher(fa:fa-download FetcherAgent)
        Reader(fa:fa-book-open ReaderAgent)
        PreFilter(fa:fa-filter PreFilterAgent)
        Metrician(fa:fa-ruler-combined MetricianAgent)
        Analyst(fa:fa-chart-pie AnalystAgent)
        Debater(fa:fa-comments DebaterAgent)
        Synthesiser(fa:fa-file-alt SynthesiserAgent)
        Reviewer(fa:fa-user-check ReviewerAgent)
    end

    CLI_Seed --> |"Inserts Task"| TaskQueue
    CLI_Manage --> |"Manages Agents"| Orchestrator

    Orchestrator --> |"Spawns/Stops"| Agent Swarm
    Scheduler --> |"Reads"| TaskQueue
    Scheduler --> |"Reads"| AgentDirectory
    Scheduler --> |"Reads"| KarmaLedger
    Scheduler --> |"Assigns Task"| Fetcher

    Fetcher --> |Emits 'Summarise_Paper' & 'Filter_Pages'| TaskQueue
    TaskQueue --> |Assigns| Reader
    TaskQueue --> |Assigns| PreFilter

    PreFilter --> |Emits 'Extract_Metrics'| TaskQueue
    Reader -.-> |(Optional) Emits 'Extract_Metrics'| TaskQueue

    TaskQueue --> |Assigns| Metrician
    Metrician --> |Emits 'Compare_Methods'| TaskQueue

    TaskQueue --> |Assigns| Analyst
    Analyst --> |Emits 'Critique_Claim'| TaskQueue

    TaskQueue --> |Assigns| Debater
    Debater --> |Emits 'Synthesise_Report'| TaskQueue

    TaskQueue --> |Assigns| Synthesiser

    Agent Swarm --> |"Work is done"| TaskQueue
    TaskQueue -.-> |"Artifact needs review"| Reviewer
    Reviewer --> |"Assigns Karma"| KarmaLedger
```

## Recent Improvements

### Enhanced Data Flow
- Fixed session propagation to ensure all tasks in a workflow share the same session ID
- Implemented proper data forwarding between agents (summaries, metrics, claims, etc.)
- Added task deduplication to prevent duplicate processing

### Intelligent Analysis
- `AnalystAgent` now generates meaningful claims from metrics using LLM
- `DebaterAgent` provides balanced critique of these claims with pros and cons
- `SynthesiserAgent` creates comprehensive reports that integrate all findings

### Multi-Modal Capabilities
- Added image extraction from PDFs using PyMuPDF
- Images are included in the final report with thumbnails
- Support for both primary (PyMuPDF) and fallback (PyPDF2) extraction methods

### Improved Report Generation
- Enhanced LLM prompting for better report structure and content
- Reports now include executive summary, metrics analysis, method comparison, and critical analysis
- Final reports are saved to session-specific directories for easy access

## Setup and Installation

**Prerequisites:**
*   Python 3.11+
*   Poetry for dependency management (`pip install poetry`)
*   A running PostgreSQL server

1.  **Clone the Repository**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-name>
    ```

2.  **Set Up Environment Variables**
    Create a file named `.env` in the root of the project and add the following, replacing the placeholder values:
    ```env
    # Connection string for your PostgreSQL database
    DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname

    # Credentials for Azure OpenAI Service
    AZURE_OPENAI_ENDPOINT="https://<your-instance>.openai.azure.com/"
    AZURE_OPENAI_API_KEY="<your-api-key>"
    ```

3.  **Install Dependencies**
    Use Poetry to install all required packages from `pyproject.toml`.
    ```bash
    poetry install
    ```
    This will also install `pdfplumber` for enhanced PDF table detection and `PyMuPDF` for image extraction.

## Running the System

Running the platform involves three main steps: starting the orchestrator, spawning the agents, and seeding the first task.

**Step 1: Start the Orchestrator**

The orchestrator is the central nervous system. It manages the agent lifecycle, runs the task scheduler, and exposes the management API. The first time it runs, it will also create all the necessary database tables.

```bash
uv run python app/orchestrator/orchestrator.py
```
You should see output indicating the server has started, and the management API is available at `http://localhost:8000`. Keep this terminal window running.

**Step 2: Spawn the Agent Swarm**

Open a *new terminal window*. Use the `manage_swarm.py` script to create the agents that will do the work.

**Example A: Basic Swarm**
This command spawns one of each type of agent required for the pipeline.

```bash
# Spawn the essential agents
uv run python scripts/manage_swarm.py add --agent-class FetcherAgent
uv run python scripts/manage_swarm.py add --agent-class ReaderAgent
uv run python scripts/manage_swarm.py add --agent-class PreFilterAgent
uv run python scripts/manage_swarm.py add --agent-class MetricianAgent
uv run python scripts/manage_swarm.py add --agent-class AnalystAgent
uv run python scripts/manage_swarm.py add --agent-class DebaterAgent
uv run python scripts/manage_swarm.py add --agent-class SynthesiserAgent
uv run python scripts/manage_swarm.py add --agent-class ReviewerAgent
```

**Example B: Specialized Swarm**
This demonstrates how to create agents with custom configurations. Here, we create two specialized debaters: one optimist and one skeptic.

```bash
# Add an "optimist" debater
uv run python scripts/manage_swarm.py add --agent-class DebaterAgent --base-id optimist-deb --config '{"debate_strategy": "optimist_only"}'

# Add a "skeptic" debater
uv run python scripts/manage_swarm.py add --agent-class DebaterAgent --base-id skeptic-deb --config '{"debate_strategy": "skeptic_only"}'
```

You can check that your agents are running with:
```bash
uv run python scripts/manage_swarm.py list
```

**Step 3: Submit an Initial Task**

Open a *third terminal window*. Use the `seed_task.py` script to give the swarm its first job.

```bash
uv run python scripts/seed_task.py "https://arxiv.org/pdf/2305.14314"
```
This will insert a `Fetch_Paper` task into the database. The scheduler will pick it up and assign it to a `FetcherAgent`, kicking off the entire pipeline.

## Agent Configuration Reference

| Agent              | Config Key                    | Type          | Default Value                                   | Description                                                                                             |
| ------------------ | ----------------------------- | ------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **FetcherAgent**   | `user_agent`                  | `string`      | `"DefaultResearchAgent/1.0"`                    | The User-Agent string to use for HTTP requests.                                                         |
| **ReaderAgent**    | `summary_prompt`              | `string`      | `"You are an expert ML researcher..."`            | The system prompt for the summarization LLM.                                                            |
|                    | `summary_model`               | `string`      | `"gpt-4o-mini-2"`                               | The name of the LLM model to use for summaries.                                                         |
|                    | `emit_metrics`                | `bool`        | `False`                                         | If `True`, emits a legacy `Extract_Metrics` task (usually redundant).                                     |
| **PreFilterAgent** | `filter_keywords`             | `list[str]`   | `["bleu", "rouge", ...]`                        | Keywords to score pages for metric-likelihood.                                                          |
|                    | `max_pages`                   | `int`         | `8`                                             | The maximum number of top-scoring pages to include in the text snippet.                                 |
| **MetricianAgent** | `metric_patterns`             | `list[dict]`  | `[{"metric": "Accuracy", ...}]`                 | A list of `{"metric": name, "pattern": regex}` dicts to override default metric extraction.           |
| **AnalystAgent**   | `focus_metrics`               | `list[str]`   | `None`                                          | A list of metric names (lowercase) to filter for. If set, all other metrics will be ignored.          |
| **DebaterAgent**   | `debate_strategy`             | `string`      | `"balanced"`                                    | Can be `"balanced"`, `"optimist_only"`, or `"skeptic_only"`. Controls the debate style.                  |
| **Synthesiser...** | `report_template`             | `string`      | `"# PEFT Research Report..."`                    | A format-string for the final markdown report. Available placeholders: `{agent_id}`, `{timestamp}`.       |
| **ReviewerAgent**  | `evaluation_prompt_template`  | `string`      | `"# You are a meticulous reviewer..."`           | The prompt template defining the rubric for quality reviews.                                            |
|                    | `base_reward`                 | `int`         | `3`                                             | The base karma reward that gets multiplied by the LLM's quality score.                                  | 