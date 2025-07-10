Below is a “happy-path” walkthrough that you can paste into your terminal, plus a plain-English description of what the swarm will do at each stage.

────────────────────────────────────────
0.  One-time prerequisites
────────────────────────────────────────
• Have Python 3.11+ (only if you’re running without Docker)  
• A Supabase Postgres URL (DATABASE_URL)  
• An OpenAI key (OPENAI_API_KEY) with “gpt-4o-mini” access

Put both secrets in a file called `.env` (copy from `.env.example`).

```
OPENAI_API_KEY="sk-…"
DATABASE_URL="postgresql+asyncpg://USER:PWD@HOST:5432/db?sslmode=require"
```

────────────────────────────────────────
1.  Run with uv (local dev)
────────────────────────────────────────
```bash
# A) install uv once
curl -LsSf https://astral.sh/uv/install.sh | sh    # < 5 s

# B) create env + install deps (first time only)
uv venv
uv pip sync          # You need to have requirements.txt or requirements.lock
    or
uv pip install -e .   # tells uv to read pyproject.toml (Install the project itself by reading pyproject.toml)

# C) export your secrets into the shell
export $(cat .env | xargs)

# D) start the pipeline on a sample PDF
python scripts/run_pipeline.py \
  --url https://arxiv.org/pdf/2106.09685.pdf
```

The script:
1. creates (if missing) the Postgres tables for `tasks`, `agents`, and `karma`,
2. boots the orchestrator runtime (spawns all micro-agents),
3. enqueues an initial `Fetch_Paper` task for the given arXiv PDF.

────────────────────────────────────────
2.  Run everything in Docker (alternative)
────────────────────────────────────────
```bash
cp .env.example .env     # add your keys
docker compose up --build
```
Compose spins up:
• `postgres` (port 5432)  
• `app`  (our code inside Python 3.11 + uv)

The container automatically runs the same `run_pipeline.py` script with the default sample PDF.

────────────────────────────────────────
3.  What happens inside – step by step
────────────────────────────────────────
1. **Scheduler** pops the `Fetch_Paper` task and chooses `fetcher-1`
   (karma is currently 0 for everyone → alphabetical tie-break).
2. **Fetcher-1**
   • downloads the PDF to `data/corpus/⧉hash.pdf`  
   • pushes `Summarise_Paper` task  
   • logs a +2 karma delta
3. **Reader-1** splits the PDF text into ≤3 k-token chunks and calls GPT-4o-mini.  
   • produces a 5-bullet summary artifact  
   • enqueues `Extract_Metrics` (+3 karma)
4. **Metrician-1** scans the text with regex, extracts things like  
   `accuracy 87.2 on SST-2`, `perplexity 5.3`, etc.  
   • stores JSON metrics artifact  
   • enqueues `Compare_Methods` (+2 karma if at least one metric found)
5. **Analyst-1** converts metrics into a Markdown table (one row per metric)  
   • artifact name `comparison`  
   • enqueues `Critique_Claim` (+2 karma)
6. **Debater** runs two OpenAI calls: “optimist” + “skeptic” personas.  
   • merges bullet lists into `{pros: […], cons: […]}` JSON  
   • enqueues `Synthesise_Report` (+2 karma)
7. **Synthesiser** stamps a minimal final report:

```
# PEFT Research Report

Generated: 2025-07-03T12:34:56Z

(This is a placeholder synthesis in the MVP.)

Earlier artifacts (summary, metrics table, critique) are available in the task log.
```

   • +1 karma, pipeline ends (queue empty).

────────────────────────────────────────
4.  How to inspect results
────────────────────────────────────────
• Redis keys contain every raw `Task` JSON (helpful for debugging).  
• Postgres table `karma_events` (in Supabase) shows delta history.  
• The console log prints “…completed” messages as each agent finishes.  
• For a quick look at the final report artifact, grep the log:

```
grep -A2 "produced final report"  app  # displays Markdown text
```

────────────────────────────────────────
5.  Changing the input
────────────────────────────────────────
Run the script again with any PDF URL (ACL, arXiv, etc.):

```bash
python scripts/run_pipeline.py --url https://arxiv.org/pdf/2404.01234.pdf
```

Agents’ karma persists in Supabase, so over multiple runs the scheduler will
start favouring the most reliable performers.

That’s the full flow—copy/paste the commands above and watch the swarm do its job.