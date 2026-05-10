import json
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from sqlmodel import Session

from app.agents.compression import CompressionAgent
from app.agents.critique import CritiqueAgent
from app.agents.decomposition import DecompositionAgent
from app.agents.rag_agent import MultiHopRAGAgent
from app.agents.synthesis import SynthesisAgent
from app.core.config import settings
from app.core.context_manager import ContextManager
from app.core.llm import OllamaClient
from app.db.models import JobExecution
from app.db.sessions import engine
from app.schemas.shared_context import AgentStep, SharedContext


class Orchestrator:
    """Master orchestrator that routes agents through SharedContext."""

    def __init__(self, model: str = settings.LLM_MODEL):
        self.model = model
        self.llm = OllamaClient(model)
        self.context_manager = ContextManager()
        self.agents = {
            "decomposition_agent": DecompositionAgent(model),
            "rag_agent": MultiHopRAGAgent(model),
            "critique_agent": CritiqueAgent(model),
            "synthesis_agent": SynthesisAgent(model),
            "compression_agent": CompressionAgent(model),
        }

    async def execute(self, query: str, job_id: Optional[str] = None) -> AsyncGenerator[Dict[str, str], None]:
        context = SharedContext(
            job_id=job_id or str(uuid.uuid4()),
            original_query=query,
            max_budget=settings.MAX_CONTEXT_TOKENS,
        )
        self._create_job(context)
        yield self._sse("metadata", {"job_id": context.job_id, "status": "started"})

        max_turns = 12
        try:
            for turn in range(max_turns):
                decision = await self._get_routing_decision(context)
                agent_name = str(decision.get("agent", "")).strip()
                reasoning = str(decision.get("reasoning", "No routing rationale returned."))

                route_step = await self._append_step(
                    context,
                    "orchestrator",
                    reasoning,
                    f"route:{agent_name}",
                    decision,
                )
                self._persist_context(context, "running")
                yield self._sse("log", route_step.model_dump(mode="json"))

                if agent_name not in self.agents:
                    agent_name = "synthesis_agent" if context.history else "decomposition_agent"

                if not await self._ensure_budget(context):
                    yield self._sse(
                        "agent",
                        {"agent": "compression_agent", "output": context.compression_events[-1]},
                    )

                output = await self._call_agent(agent_name, context)
                agent_step = await self._append_step(
                    context,
                    agent_name,
                    f"{agent_name} completed turn {turn + 1}.",
                    "process_context",
                    output,
                )
                self._persist_context(context, "running")
                yield self._sse("agent", agent_step.model_dump(mode="json"))

                if agent_name == "synthesis_agent" and context.final_answer:
                    self._persist_context(context, "completed")
                    yield self._sse(
                        "final",
                        {
                            "job_id": context.job_id,
                            "answer": context.final_answer,
                            "provenance_map": context.provenance_map,
                        },
                    )
                    return

            self._persist_context(context, "failed")
            yield self._sse("error", {"job_id": context.job_id, "message": "Max turns exceeded"})
        except Exception as exc:
            self._persist_context(context, "failed", error=str(exc))
            yield self._sse("error", {"job_id": context.job_id, "message": str(exc)})

    async def _call_agent(self, agent_name: str, context: SharedContext) -> Dict[str, Any]:
        agent = self.agents[agent_name]
        return await agent.process(context)

    async def _get_routing_decision(self, context: SharedContext) -> Dict[str, Any]:
        prompt = f"""
You are the Master Orchestrator for Mega AI. Decide the single next agent.
Use structured reasoning; do not follow a fixed chain. Agents communicate only through SharedContext.

Available agents:
- decomposition_agent: create or revise task DAG.
- rag_agent: gather evidence and perform multi-hop reasoning.
- critique_agent: score claims and flag spans.
- synthesis_agent: produce final answer and provenance map.

Routing requirements:
- Do not choose synthesis_agent until the context contains prior agent output.
- For questions about abbreviations, current systems, technical facts, or "why this system uses it",
  gather evidence or decompose first so ambiguous terms are resolved in context.
- Prefer critique_agent before synthesis_agent when a candidate answer exists.

SharedContext state:
original_query={context.original_query}
tasks={context.tasks}
route_state={context.route_state}
history={[{"agent": step.agent_id, "action": step.action} for step in context.history]}
has_tool_results={bool(context.tool_results)}
has_final_answer={bool(context.final_answer)}

Return ONLY JSON:
{{"agent": "agent_name", "reasoning": "short justification"}}
"""
        fallback = self._fallback_route(context)
        decision = await self.llm.generate_json(prompt, fallback=fallback, timeout=180.0)
        if decision.get("agent") not in self.agents or decision.get("agent") == "compression_agent":
            return fallback
        if decision.get("agent") == "synthesis_agent" and not context.route_state.get("critique_complete"):
            return fallback
        return decision

    def _fallback_route(self, context: SharedContext) -> Dict[str, str]:
        state = context.route_state
        if not state.get("decomposed"):
            agent = "decomposition_agent"
        elif not state.get("rag_complete"):
            agent = "rag_agent"
        elif not state.get("critique_complete"):
            agent = "critique_agent"
        else:
            agent = "synthesis_agent"
        return {
            "agent": agent,
            "reasoning": "Fallback route selected because LLM routing was unavailable or invalid.",
        }

    async def _ensure_budget(self, context: SharedContext) -> bool:
        serialized = json.dumps([step.model_dump(mode="json") for step in context.history])
        tokens = self.context_manager.count_tokens(serialized)
        context.total_tokens = tokens
        if tokens <= context.max_budget:
            return True
        await self.agents["compression_agent"].process(context)
        return False

    async def _append_step(
        self,
        context: SharedContext,
        agent_id: str,
        thought: str,
        action: str,
        output: Any,
    ) -> AgentStep:
        token_text = f"{agent_id} {thought} {action} {output}"
        tokens = self.context_manager.count_tokens(token_text)
        step = AgentStep(
            agent_id=agent_id,
            thought=thought,
            action=action,
            output=output,
            tokens_used=tokens,
        )
        context.history.append(step)
        context.total_tokens += tokens
        return step

    def _create_job(self, context: SharedContext) -> None:
        try:
            with Session(engine) as session:
                session.add(
                    JobExecution(
                        id=context.job_id,
                        query=context.original_query,
                        status="pending",
                        trace=context.model_dump(mode="json"),
                    )
                )
                session.commit()
        except Exception:
            pass

    def _persist_context(self, context: SharedContext, status: str, error: Optional[str] = None) -> None:
        try:
            with Session(engine) as session:
                job = session.get(JobExecution, context.job_id)
                if not job:
                    return
                job.status = status
                trace = context.model_dump(mode="json")
                if error:
                    trace["error"] = error
                job.trace = trace
                session.add(job)
                session.commit()
        except Exception:
            pass

    def _sse(self, event: str, data: Dict[str, Any]) -> Dict[str, str]:
        return {"event": event, "data": json.dumps(data)}
