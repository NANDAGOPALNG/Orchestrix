from typing import Any, Dict, List

from app.core.llm import OllamaClient
from app.schemas.shared_context import SharedContext
from app.tools.self_reflection import SelfReflectionTool


class CritiqueAgent:
    """Scores claims and flags spans that need caution or correction."""

    def __init__(self, model: str):
        self.llm = OllamaClient(model)
        self.reflection = SelfReflectionTool(model)

    async def process(self, context: SharedContext) -> Dict[str, Any]:
        latest = self._latest_rag_output(context)
        prompt = f"""
Critique the following candidate answer.
Assign confidence per claim, flag exact text spans that are unsupported, risky, or ambiguous.
Return JSON:
{{
  "claim_scores": [{{"claim": "...", "confidence": 0.0, "rationale": "..."}}],
  "flagged_spans": [{{"text": "...", "reason": "...", "severity": "low|medium|high"}}],
  "overall_confidence": 0.0
}}

Candidate:
{latest}
"""
        fallback = {
            "claim_scores": [
                {
                    "claim": "Candidate answer requires verification.",
                    "confidence": 0.35,
                    "rationale": "Critique LLM unavailable or returned invalid JSON.",
                }
            ],
            "flagged_spans": [],
            "overall_confidence": 0.35,
        }
        critique = await self.llm.generate_json(prompt, fallback=fallback)
        reflection = await self.reflection.run(str(latest), context.original_query)
        critique["reflection"] = reflection.model_dump(mode="json")
        context.tool_results[f"self_reflection:{len(context.tool_results)}"] = reflection.model_dump(mode="json")
        context.route_state["critique_complete"] = True
        return critique

    def _latest_rag_output(self, context: SharedContext) -> Dict[str, Any]:
        for step in reversed(context.history):
            if step.agent_id == "rag_agent":
                return step.output
        return {"answer": "", "claims": []}
