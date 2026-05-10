
# Mega AI

Real-Time Multi-Agent LLM Orchestration and Evaluation System

Mega AI is a containerized, local-first multi-agent orchestration prototype built with FastAPI, PostgreSQL, SQLModel, Server-Sent Events, and Ollama. It demonstrates dynamic LLM-based routing, shared-context agent handoffs, structured tool failure handling, trace logging, context budgeting, and a custom evaluation harness.

This project was built for the LLM Engineer take-home assessment.

## Features

- Multi-agent orchestration through a master orchestrator
- SharedContext schema for all inter-agent communication
- Dynamic LLM-based routing with fallback guards
- Server-Sent Events streaming via `sse-starlette`
- PostgreSQL-backed execution traces with SQLModel
- Retryable tool interfaces with explicit failure contracts
- Context budget tracking and compression agent
- Custom 15-case evaluation harness
- Meta-agent that proposes prompt diffs from failed eval cases
- Docker Compose setup for API and PostgreSQL
- Local Ollama integration via HTTP

## Tech Stack

- Python
- FastAPI
- SQLModel
- PostgreSQL
- Docker Compose
- Ollama
- httpx
- sse-starlette
- tiktoken
- uv

## Architecture

```text
Client
  |
  | POST /query
  v
FastAPI SSE Endpoint
  |
  v
Master Orchestrator
  |
  |-- reads/writes SharedContext
  |-- makes LLM-based routing decisions
  |-- logs every routing decision and agent output
  |
  +--> DecompositionAgent
  |      Creates typed task DAGs for ambiguous or complex queries
  |
  +--> MultiHopRAGAgent
  |      Performs multi-hop retrieval-style reasoning and citation mapping
  |
  +--> CritiqueAgent
  |      Scores claims, flags weak spans, and calls self-reflection
  |
  +--> SynthesisAgent
  |      Produces final answer and provenance map
  |
  +--> CompressionAgent
         Summarizes conversational history when context budget is exceeded

Tools
  |
  +--> SearchTool
  +--> PythonTool
  +--> SQLTool
  +--> SelfReflectionTool

Persistence
  |
  +--> JobExecution table
  +--> EvaluationRun table
  +--> PromptVersion table
```

## Agents

### Master Orchestrator

The orchestrator owns execution flow. It does not use a fixed hardcoded chain as the primary control path. Instead, it asks the local LLM to choose the next agent using structured JSON routing. If routing fails, returns invalid JSON, or selects an unsafe step, deterministic fallback routing is used.

Every routing decision is logged to `JobExecution.trace`.

### DecompositionAgent

Breaks the user query into a task DAG with dependencies. This is used to clarify ambiguous or multi-step requests before retrieval and synthesis.

### MultiHopRAGAgent

Plans at least two retrieval/reasoning hops, calls the search tool, stores tool results in `SharedContext.tool_results`, and generates a candidate answer with citations where available.

If search fails or returns empty results, the agent records structured fallback data instead of pretending retrieval succeeded.

### CritiqueAgent

Reviews candidate outputs, assigns confidence scores, flags risky spans, and calls the self-reflection tool. Critique results are stored in the shared context trace.

### SynthesisAgent

Merges previous agent outputs into a final answer and builds a provenance map linking answer content to source agents and citations.

### CompressionAgent

Used by the context manager when history exceeds the token budget. It compresses conversational history while preserving structured tool outputs, citations, and scores losslessly in `SharedContext.tool_results`.

## Tools

All tools follow a structured failure contract with a two-retry limit.

### SearchTool

Attempts web-style lookup through DuckDuckGo's public instant-answer endpoint. Returns structured results with title, URL, and snippet.

Failure modes:
- timeout
- empty results
- network error

Fallback returns a structured object with:
- query
- last error
- attempts
- fallback message

### PythonTool

Runs constrained Python snippets in a restricted namespace. Blocks unsafe operations such as filesystem access, subprocess usage, sockets, and dynamic imports.

Failure modes:
- malformed code
- blocked operation
- runtime exception

### SQLTool

Runs read-only SQL queries against the configured database. Only `SELECT` statements are allowed.

Failure modes:
- non-SELECT query
- malformed SQL
- database connection failure

### SelfReflectionTool

Uses the LLM to re-read prior content and identify issues. If the LLM fails, it returns a heuristic fallback with low confidence.

## API Endpoints

The application exposes the required five primary endpoints.

### 1. Submit Query

```http
POST /query
```

Streams agent activity and final response using SSE.

Example:

```powershell
Set-Content -Path .\body.json -Value '{"query":"Explain what SSE is and why this system uses it."}' -NoNewline

curl.exe -N -X POST "http://localhost:8000/query" `
  -H "Content-Type: application/json" `
  --data-binary "@body.json"
```

### 2. Retrieve Execution Trace

```http
GET /trace/{job_id}
```

Returns the persisted execution trace for a job.

Example:

```powershell
curl.exe http://localhost:8000/trace/YOUR_JOB_ID
```

### 3. Evaluation Summary

```http
GET /eval/summary
```

Returns aggregate evaluation results stored in the database.

Example:

```powershell
curl.exe http://localhost:8000/eval/summary
```

### 4. Prompt Approval

```http
POST /prompts/approve
```

Approves and stores a new active prompt version for an agent.

Example:

```powershell
curl.exe -X POST http://localhost:8000/prompts/approve `
  -H "Content-Type: application/json" `
  --data-raw '{"agent_id":"synthesis_agent","prompt_text":"Always cite evidence and disclose uncertainty."}'
```

### 5. Re-Evaluation

```http
POST /eval/re-eval
```

Runs the evaluation harness and streams the result.

Example:

```powershell
curl.exe -N -X POST http://localhost:8000/eval/re-eval
```

## Setup

### Prerequisites

Install:

- Docker Desktop
- uv
- Ollama

Verify:

```powershell
docker --version
docker compose version
uv --version
ollama --version
```

Pull the local model:

```powershell
ollama pull llama3
```

Make sure Ollama is running:

```powershell
curl.exe http://localhost:11434/api/tags
```

If Ollama is already running, `ollama serve` may show a port-in-use error. That is expected.

## Running With Docker Compose

From the project root:

```powershell
docker compose -f docker/docker-compose.yml build --no-cache
docker compose -f docker/docker-compose.yml up
```

The API will be available at:

```text
http://localhost:8000
```

Health check:

```powershell
curl.exe http://localhost:8000/health
```

Expected response:

```json
{"status":"healthy","project":"Mega AI"}
```

## Running API Locally With uv

If Docker dependency installation fails because of network timeouts, run PostgreSQL in Docker and the API locally.

Start database:

```powershell
docker compose -f docker/docker-compose.yml up -d db
```

Run API:

```powershell
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

The system is configured through environment variables.

Default values are in `app/core/config.py`.

Important variables:

```env
PROJECT_NAME=Mega AI
DATABASE_URL=postgresql://user:password@localhost:5432/mega_ai
LLM_MODEL=llama3
OLLAMA_BASE_URL=http://localhost:11434
MAX_CONTEXT_TOKENS=4096
```

In Docker, `OLLAMA_BASE_URL` is configured as:

```env
http://host.docker.internal:11434
```

so the API container can reach Ollama running on the host machine.

## Evaluation Harness

The eval harness is implemented manually without third-party evaluation frameworks.

The test set contains 15 cases:

- 5 simple baseline queries
- 5 ambiguous queries
- 5 adversarial queries

Cases are stored in:

```text
app/eval/cases.json
```

The harness runs the full pipeline, scores outputs, stores results in PostgreSQL, and asks the MetaAgent to propose prompt diffs for failed cases.

Run:

```powershell
curl.exe -N -X POST http://localhost:8000/eval/re-eval
```

View summary:

```powershell
curl.exe http://localhost:8000/eval/summary
```

## Observability

Every orchestration step is appended to `SharedContext.history` and persisted to the `JobExecution` table.

Trace data includes:

- job ID
- original query
- routing decisions
- agent thoughts
- agent actions
- agent outputs
- tool results
- token counts
- final answer
- provenance map

Retrieve trace:

```powershell
curl.exe http://localhost:8000/trace/YOUR_JOB_ID
```

## AI Collaboration Attestation

AI assistance was used during development for:

- scaffolding agent implementations
- designing structured tool failure contracts
- building the orchestration loop
- drafting evaluation cases
- debugging Docker, PowerShell, and SSE behavior
- preparing project documentation

All generated code was reviewed, modified, and tested locally. The final implementation choices, known limitations, and submission readiness assessment were made by the developer.

## Known Limitations

This is a production-oriented prototype, not a fully hardened production system.

Current limitations:

- The orchestrator uses LLM-based routing, but fallback guards are still conservative and may route imperfectly.
- Search uses DuckDuckGo's public instant-answer endpoint and can return empty results for many queries.
- Tool failures are handled explicitly, but not every tool is deeply integrated into every route yet.
- `PythonTool` and `SQLTool` are implemented with retry/fallback contracts, but the current agent flow primarily exercises search and self-reflection.
- Evaluation scoring is custom and reproducible, but still lightweight compared to a mature human-validated eval suite.
- Prompt approval is implemented, but the full approve/reject lifecycle and targeted failed-case-only re-eval are simplified.
- Docker Compose currently runs API and PostgreSQL. A separate background worker and log UI are not fully implemented.
- SSE streams agent-level events, not true token-by-token LLM deltas.
- Some database write failures are isolated to keep demos stable, but production observability should fail louder.

## What I Would Build Next

Given more time, I would add:

- Dedicated background worker for long-running agent jobs
- Tool-selection agent that chooses Search, SQL, Python, or Reflection dynamically
- Stronger SQL natural-language-to-query planner with schema inspection
- True token-level streaming from Ollama
- Better citation scoring and contradiction resolution metrics
- Prompt rewrite approval/rejection table with full audit trail
- Targeted re-eval only on failed cases
- Structured log query dashboard
- More robust deterministic eval scoring
- Integration tests for all five endpoints
- GitHub Actions CI for compile, test, and Docker build

## Demo Flow

Recommended reviewer demo:

1. Start Ollama and pull `llama3`
2. Start the system with Docker Compose
3. Check `/health`
4. Send a query to `/query`
5. Copy the streamed `job_id`
6. Retrieve `/trace/{job_id}`
7. Run `/eval/re-eval`
8. Retrieve `/eval/summary`

Example query:

```powershell
Set-Content -Path .\body.json -Value '{"query":"Explain what SSE is and why this system uses it."}' -NoNewline

curl.exe -N -X POST "http://localhost:8000/query" `
  -H "Content-Type: application/json" `
  --data-binary "@body.json"
```


This project was created as a take-home assessment submission.
```
