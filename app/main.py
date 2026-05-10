import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI, HTTPException, Request
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.orchestrator import Orchestrator
from app.db.models import JobExecution, PromptVersion
from app.db.sessions import engine, init_db
from app.eval.harness import EvaluationHarness, eval_summary


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "project": settings.PROJECT_NAME}


@app.post("/query")
async def handle_query(request: Request) -> EventSourceResponse:
    data = await request.json()
    query = data.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    orchestrator = Orchestrator()
    return EventSourceResponse(orchestrator.execute(str(query)))


@app.get("/trace/{job_id}")
async def get_trace(job_id: str) -> Dict:
    with Session(engine) as session:
        job = session.get(JobExecution, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "job_id": job.id,
            "query": job.query,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "trace": job.trace,
        }


@app.get("/eval/summary")
async def get_eval_summary() -> Dict:
    return eval_summary()


@app.post("/prompts/approve")
async def approve_prompt(request: Request) -> Dict:
    data = await request.json()
    agent_id = data.get("agent_id")
    prompt_text = data.get("prompt_text")
    if not agent_id or not prompt_text:
        raise HTTPException(status_code=400, detail="agent_id and prompt_text are required")

    with Session(engine) as session:
        active_versions = session.exec(
            select(PromptVersion).where(
                PromptVersion.agent_id == agent_id,
                PromptVersion.is_active == True,  # noqa: E712
            )
        ).all()
        for version in active_versions:
            version.is_active = False
            session.add(version)
        latest = session.exec(
            select(PromptVersion).where(PromptVersion.agent_id == agent_id)
        ).all()
        next_version = max((item.version for item in latest), default=0) + 1
        prompt = PromptVersion(
            agent_id=str(agent_id),
            prompt_text=str(prompt_text),
            version=next_version,
            is_active=True,
        )
        session.add(prompt)
        session.commit()
        session.refresh(prompt)
        return {
            "id": prompt.id,
            "agent_id": prompt.agent_id,
            "version": prompt.version,
            "is_active": prompt.is_active,
        }


@app.post("/eval/re-eval")
async def re_eval() -> EventSourceResponse:
    async def stream() -> AsyncGenerator[Dict[str, str], None]:
        harness = EvaluationHarness()
        yield {"event": "metadata", "data": json.dumps({"status": "started"})}
        summary = await harness.run_all()
        yield {"event": "final", "data": json.dumps(summary)}

    return EventSourceResponse(stream())
