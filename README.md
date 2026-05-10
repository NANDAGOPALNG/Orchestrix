# Mega AI

**Real-Time Multi-Agent LLM Orchestration and Evaluation System**

Mega AI is a containerized, local-first multi-agent system built with FastAPI, PostgreSQL, SQLModel, Server-Sent Events, and Ollama. It implements dynamic LLM-based routing, a shared-context inter-agent communication schema, structured tool failure handling, context budget enforcement, and a fully custom evaluation harness with a self-improving prompt loop.

---

## Table of Contents

- [Architecture](#architecture)
- [Agents](#agents)
- [Tools](#tools)
- [Context Budget Management](#context-budget-management)
- [Evaluation Pipeline](#evaluation-pipeline)
- [Self-Improving Prompt Loop](#self-improving-prompt-loop)
- [Streaming and Observability](#streaming-and-observability)
- [API Reference](#api-reference)
- [Setup and Running](#setup-and-running)
- [Environment Variables](#environment-variables)
- [Known Limitations](#known-limitations)
- [What I Would Build Next](#what-i-would-build-next)
- [AI Collaboration Attestation](#ai-collaboration-attestation)

---

## Architecture

```
Client
  |
  | POST /query
  v
FastAPI SSE Endpoint
  |
  v
Master Orchestrator
  |  LLM-based routing decision (structured JSON) per turn
  |  Every decision logged to SharedContext.history and persisted to PostgreSQL
  |
  +--> DecompositionAgent      Parses query into typed task DAG with dependency resolution
  |
  +--> MultiHopRAGAgent        Two-hop retrieval reasoning with per-chunk citation mapping
  |
  +--> CritiqueAgent           Span-level confidence scoring and self-reflection tool call
  |
  +--> SynthesisAgent          Merges outputs, resolves contradictions, builds provenance map
  |
  +--> CompressionAgent        Triggered by ContextManager when token budget is exceeded

Tools (called by agents via SharedContext, never directly between agents)
  |
  +--> SearchTool              DuckDuckGo instant-answer stub with structured failure contract
  +--> PythonTool              Sandboxed Python execution with blocked unsafe operations
  +--> SQLTool                 Read-only SELECT execution against PostgreSQL
  +--> SelfReflectionTool      LLM re-reads prior context and surfaces contradictions

Persistence
  |
  +--> JobExecution            Full trace per job: routing decisions, agent outputs, tool calls, token counts
  +--> EvaluationRun           Per-case scores and justifications per eval run
  +--> PromptVersion           Proposed and approved prompt rewrites with approval audit trail
```

All inter-agent communication flows exclusively through a typed `SharedContext` object. Agents do not call one another. The orchestrator mediates every handoff and logs its routing rationale before each step.

---

## Agents

### Master Orchestrator

The orchestrator owns the full execution loop up to a maximum of 12 turns. At each turn it sends the current `SharedContext` to the local LLM and receives a JSON routing decision specifying the next agent and a justification string. If the model returns malformed JSON or selects an unregistered agent, a deterministic fallback fires: `decomposition_agent` if history is empty, `synthesis_agent` otherwise.

Every routing decision — including fallback activations — is appended as an `AgentStep` to `SharedContext.history` and written to `JobExecution.trace` in PostgreSQL before the next agent is invoked. This means the exact decision sequence is always recoverable from the database regardless of whether the job completed successfully.

### DecompositionAgent

Accepts the raw user query and produces a structured task DAG stored in `SharedContext.tasks`. Each task node carries a type, a description, and a list of dependency task IDs. The orchestrator uses this DAG when ambiguous or multi-step queries arrive, ensuring dependent sub-tasks are not scheduled before their predecessors resolve.

### MultiHopRAGAgent

Plans a minimum of two retrieval hops before forming a candidate answer. On each hop, it calls `SearchTool`, stores the result in `SharedContext.tool_results`, and uses the accumulated evidence for the next reasoning step. The final candidate answer includes a citation list mapping each claim to the specific chunk that contributed it. If search fails at any hop, a structured fallback object is stored rather than silently proceeding as if retrieval succeeded.

### CritiqueAgent

Receives the candidate answer from the RAG agent and reviews it at the span level. It assigns a numeric confidence score to each factual claim and flags specific spans it disagrees with, not the output as a whole. After scoring, it calls `SelfReflectionTool` to cross-check critique results against prior session context. All critique output is stored in `SharedContext.history` for the synthesis agent to consume.

### SynthesisAgent

Reads all prior `AgentStep` entries in `SharedContext.history`, resolves contradictions flagged by the critique agent, and produces the final answer. It also builds `SharedContext.provenance_map`, a dictionary linking each sentence index in the final answer to the source agent and source chunk that produced it. The provenance map is included in the SSE `final` event payload.

### CompressionAgent

Invoked by the `ContextManager` when `SharedContext.total_tokens` would exceed `max_budget` after a pending addition. It summarizes conversational history entries (lossy) while leaving all structured fields — `tool_results`, citation lists, confidence scores — untouched (lossless). Compression events are logged to `SharedContext.compression_events`.

---

## Tools

All tools share a base interface with a two-retry limit. Each retry is logged separately with its own input, output, latency, and outcome. An agent that receives a tool result and deems it insufficient can re-call with a modified input; the decision to retry is explicit in agent logic, not embedded in a prompt instruction.

Every tool call is stored with: input payload, output payload, latency in milliseconds, attempt number, whether fallback was used, and whether the calling agent accepted or rejected the result.

### SearchTool

Queries DuckDuckGo's public instant-answer endpoint and returns a list of structured results containing title, URL, and snippet. Failure modes:

| Failure condition | Return value |
|---|---|
| Network timeout | `ToolResult(ok=False, error="timeout", fallback_used=True)` |
| Empty results | `ToolResult(ok=False, error="empty_results", fallback_used=True)` |
| HTTP error | `ToolResult(ok=False, error="http_{status}", fallback_used=True)` |

### PythonTool

Executes Python snippets in a restricted namespace. Blocked operations: filesystem access, `subprocess`, `socket`, dynamic imports via `__import__`. Returns `stdout`, `stderr`, and exit code. Failure modes:

| Failure condition | Return value |
|---|---|
| Blocked operation detected | `ToolResult(ok=False, error="blocked_operation")` |
| Runtime exception | `ToolResult(ok=False, error=repr(exception))` |
| Malformed code | `ToolResult(ok=False, error="syntax_error")` |

### SQLTool

Runs read-only `SELECT` queries against the configured PostgreSQL database. Rejects any statement that is not a `SELECT` before execution. Failure modes:

| Failure condition | Return value |
|---|---|
| Non-SELECT statement | `ToolResult(ok=False, error="non_select_rejected")` |
| Malformed SQL | `ToolResult(ok=False, error="sql_syntax_error")` |
| Connection failure | `ToolResult(ok=False, error="db_connection_error")` |

### SelfReflectionTool

Sends prior context content to the LLM and asks it to identify inconsistencies. Returns a structured object with flagged spans and a confidence score. If the LLM call fails, returns a heuristic fallback marked with `confidence: low`.

---

## Context Budget Management

The `ContextManager` uses `tiktoken` to count tokens against each agent's declared budget before content is added to `SharedContext`. The check is explicit: any agent can call `check_budget(context, new_text)` to see whether adding that text would breach `max_budget`. If it would, the orchestrator invokes `CompressionAgent` before proceeding.

Agents that bypass the budget check and cause an overflow are caught post-hoc and logged as policy violations in the trace, not silently truncated. Policy violations are queryable via `GET /trace/{job_id}`.

Configuration:

```
MAX_CONTEXT_TOKENS=4096   # adjustable via environment variable
```

---

## Evaluation Pipeline

The evaluation harness runs 15 test cases through the full orchestration pipeline without relying on any third-party eval framework. All scoring logic is implemented from scratch. Cases are stored in `app/eval/cases.json` and divided into three categories:

| Category | Count | Purpose |
|---|---|---|
| Simple (baseline) | 5 | Queries with known correct answers; establishes baseline scores |
| Ambiguous | 5 | Underspecified inputs that test decomposition quality and assumption handling |
| Adversarial | 5 | Prompt injections, confident wrong premises, and critique-synthesis contradiction traps |

Each test case is scored across six dimensions:

| Dimension | What it measures |
|---|---|
| Answer correctness | Coverage of expected traits in the final answer |
| Citation accuracy | Whether retrieved chunks are cited and attributable |
| Contradiction resolution | Whether critique-flagged contradictions are resolved in synthesis |
| Tool selection efficiency | Penalizes unnecessary tool calls relative to query complexity |
| Context budget compliance | Whether token limits were respected throughout the job |
| Critique agreement rate | Whether the critique agent's confidence scores align with the final output |

Every dimension produces a numeric score and a written justification string. Aggregate scores and per-case justifications are stored in the `EvaluationRun` table with the full prompt sent to each agent, every tool call made, every output received, and a timestamp. Re-running eval on the same inputs produces a diff-able result because all runs are persisted independently.

---

## Self-Improving Prompt Loop

After each eval run, the `MetaAgent` reads all cases where `score < 0.7`, identifies the worst-performing agent-prompt combination by scoring dimension, and proposes a rewritten prompt. The proposed rewrite is stored in the `PromptVersion` table with a structured diff and a justification string. It is never automatically applied.

The approval lifecycle:

1. `POST /eval/re-eval` runs the harness and triggers `MetaAgent` to propose rewrites for failures.
2. A human reviews the proposed diff via `GET /eval/summary`.
3. `POST /prompts/approve` approves or rejects the rewrite, recording the decision with a timestamp.
4. If approved, `POST /eval/re-eval` re-runs only the previously failed cases using the new prompt and logs the score delta.

Every proposed rewrite, every approval or rejection, and every performance delta is stored with timestamps and is queryable. The full audit trail is recoverable from the `PromptVersion` table.

---

## Streaming and Observability

Agent outputs are streamed via Server-Sent Events. The client receives typed events as the pipeline executes:

| Event type | Content |
|---|---|
| `metadata` | Job ID and status on start |
| `log` | Orchestrator routing decision with agent name and reasoning |
| `agent` | Agent step output including thought, action, and result |
| `final` | Final answer, provenance map, and job ID |
| `error` | Machine-readable error code, human-readable message, and job ID |

Structured logging uses a consistent per-event schema: timestamp, agent ID, event type, input hash, output hash, latency, token count, and policy violations if any.

Retrieve the full execution trace for any job:

```
GET /trace/{job_id}
```

The trace response reconstructs the exact sequence of orchestrator routing decisions, agent steps, tool calls with retry history, compression events, and token counts in chronological order.

---

## API Reference

### POST /query

Submit a query and receive a streaming SSE response.

Request body:

```json
{ "query": "your query here" }
```

Example (Linux/macOS):

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain what SSE is and why this system uses it."}'
```

Example (Windows PowerShell):

```powershell
Set-Content -Path .\body.json -Value '{"query":"Explain what SSE is and why this system uses it."}' -NoNewline
curl.exe -N -X POST "http://localhost:8000/query" -H "Content-Type: application/json" --data-binary "@body.json"
```

---

### GET /trace/{job_id}

Retrieve the full execution trace for a completed job.

```bash
curl http://localhost:8000/trace/YOUR_JOB_ID
```

---

### GET /eval/summary

Retrieve the latest evaluation run summary broken down by test category and scoring dimension.

```bash
curl http://localhost:8000/eval/summary
```

---

### POST /prompts/approve

Submit a human approval or rejection for a pending prompt rewrite.

```bash
curl -X POST http://localhost:8000/prompts/approve \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "synthesis_agent", "prompt_text": "Always cite evidence and disclose uncertainty."}'
```

---

### POST /eval/re-eval

Trigger evaluation on all cases (or previously failed cases if approved prompts exist) and stream results.

```bash
curl -N -X POST http://localhost:8000/eval/re-eval
```

---

All error responses include:

```json
{
  "error_code": "MACHINE_READABLE_CODE",
  "message": "Human-readable explanation.",
  "job_id": "uuid-if-applicable"
}
```

---

## Setup and Running

### Prerequisites

Install the following:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.com)

Verify installations:

```bash
docker --version
docker compose version
uv --version
ollama --version
```

Pull the local model:

```bash
ollama pull llama3
```

Confirm Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

If `ollama serve` reports a port-in-use error, Ollama is already running in the background. That is expected.

---

### Running with Docker Compose (recommended)

From the project root:

```bash
docker compose -f docker/docker-compose.yml build --no-cache
docker compose -f docker/docker-compose.yml up
```

The API will be available at `http://localhost:8000`.

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{ "status": "healthy", "project": "Mega AI" }
```

---

### Running the API Locally (fallback)

If Docker dependency installation fails due to network timeouts, run PostgreSQL in Docker and the API locally with `uv`.

Start the database:

```bash
docker compose -f docker/docker-compose.yml up -d db
```

Run the API:

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

### Recommended Reviewer Demo Flow

1. Start Ollama and confirm `llama3` is pulled.
2. Start the system with Docker Compose.
3. `GET /health` — confirm the API is up.
4. `POST /query` with a test query — note the streamed events and copy the `job_id` from the `metadata` event.
5. `GET /trace/{job_id}` — inspect the full routing and agent decision sequence.
6. `POST /eval/re-eval` — run all 15 evaluation cases.
7. `GET /eval/summary` — review scores by category and dimension.
8. `POST /prompts/approve` — approve a meta-agent-proposed prompt rewrite if one exists.

---

## Environment Variables

All configuration is through environment variables. No credentials are hardcoded anywhere in the repository.

| Variable | Default | Description |
|---|---|---|
| `PROJECT_NAME` | `Mega AI` | Project name in API responses |
| `DATABASE_URL` | `postgresql://user:password@localhost:5432/mega_ai` | PostgreSQL connection string |
| `LLM_MODEL` | `llama3` | Ollama model to use |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama HTTP endpoint |
| `MAX_CONTEXT_TOKENS` | `4096` | Per-job token budget |

In Docker Compose, `OLLAMA_BASE_URL` is set to `http://host.docker.internal:11434` so the API container can reach Ollama running on the host.

Default values are defined in `app/core/config.py`.

---

## Tech Stack

- Python 3.12
- FastAPI
- SQLModel
- PostgreSQL 15
- Docker Compose
- Ollama (local LLM inference)
- httpx
- sse-starlette
- tiktoken
- uv

---

## Known Limitations

This is a production-oriented prototype. The following are honest assessments of where the current implementation has gaps:

**Routing accuracy.** LLM-based routing works well for clear multi-step queries but can misroute on very short or highly ambiguous inputs. The deterministic fallback ensures the system does not hang, but the fallback path skips the decomposition DAG.

**Search coverage.** `SearchTool` uses DuckDuckGo's public instant-answer endpoint, which returns empty results for many technical queries. The failure contract handles this explicitly, but retrieval quality is limited compared to a proper search API.

**Tool coverage in agent paths.** `PythonTool` and `SQLTool` are fully implemented with retry and fallback contracts. In the current orchestration flow, the most common active tools are search and self-reflection. Code execution and SQL lookup are exercised primarily in adversarial and ambiguous eval cases.

**SSE granularity.** The system streams agent-level events in real time. It does not stream individual LLM tokens from Ollama, which would require tap into Ollama's streaming response endpoint and forwarding each chunk.

**Background worker.** The Docker Compose setup runs the API and PostgreSQL. A separate background worker process for long-running agent jobs is not yet extracted into its own service.

**Prompt approval loop completeness.** The approve/reject lifecycle and per-failed-case targeted re-eval are implemented. The meta-agent's proposed diffs are stored, but the diff format is a plain text comparison rather than a structured patch object.

**Eval scoring depth.** Scoring is deterministic and reproducible but lightweight. Citation accuracy and contradiction resolution scoring rely on keyword and structure checks rather than semantic similarity. A human-validated reference set would improve score reliability.

**Log query UI.** The Docker Compose spec includes a log query interface as a planned service. It is not yet implemented; trace queries go through the `/trace/{job_id}` endpoint directly.

---

## What I Would Build Next

Given additional time, the highest-value additions would be:

- **Token-level SSE streaming** by consuming Ollama's streaming API and forwarding chunks with per-agent tagging.
- **Dedicated background worker** extracted from the API process, with a job queue and status polling endpoint.
- **Dynamic tool-selection agent** that chooses among Search, SQL, Python, and Reflection at runtime based on query classification rather than routing the choice through the main orchestrator prompt.
- **NL-to-SQL planner** with schema introspection so SQLTool can handle natural-language queries without requiring the agent to write raw SQL.
- **Semantic eval scoring** using embedding similarity for citation accuracy and answer correctness dimensions, replacing the current keyword-based checks.
- **Structured prompt diff format** replacing plain text diffs with a JSON patch object that records which sentence changed, what it changed to, and the before/after score delta.
- **Full approve/reject audit table** with a queryable history of every human decision on proposed rewrites, sorted by agent and scoring dimension.
- **GitHub Actions CI** running compile checks, unit tests, and a Docker build on every push.
- **Integration test suite** covering all five endpoints with both happy-path and failure-mode assertions.

---

## AI Collaboration Attestation

AI assistance was used during development for:

- Scaffolding agent class structures and the shared context schema.
- Designing structured tool failure contracts and retry interfaces.
- Drafting and iterating on the orchestration routing loop.
- Generating the 15 evaluation cases and expected trait definitions.
- Debugging Docker networking, PowerShell curl behavior, and SSE event formatting.
- Preparing and editing project documentation.

All generated code was reviewed, understood, and tested locally before inclusion. Architecture decisions, known-limitation assessments, and submission readiness judgments were made by the developer.
