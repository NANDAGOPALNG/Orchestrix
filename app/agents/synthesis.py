from typing import Any, Dict, List

from app.core.llm import OllamaClient
from app.schemas.shared_context import SharedContext


class SynthesisAgent:
    """Merges agent outputs into a final answer and provenance map."""

    def __init__(self, model: str):
        self.llm = OllamaClient(model)

    async def process(self, context: SharedContext) -> Dict[str, Any]:
        prompt = f"""
Create the final answer from the shared context.
Respect critique warnings and include citations when available.
Return JSON:
{{
  "answer": "final answer",
  "provenance_map": {{"0": {{"source_agent": "rag_agent", "citations": []}}}},
  "residual_risks": ["..."]
}}

Original query:
{context.original_query}

History:
{[step.model_dump(mode="json") for step in context.history]}

Tool data:
{context.tool_results}
"""
        fallback_answer = self._fallback_answer(context)
        fallback = {
            "answer": fallback_answer,
            "provenance_map": {
                "0": {
                    "source_agent": "synthesis_agent",
                    "citations": self._collect_citations(context),
                }
            },
            "residual_risks": ["Generated with fallback synthesis because the LLM response was unavailable."],
        }
        output = await self.llm.generate_json(prompt, fallback=fallback)
        if not output.get("answer"):
            output = fallback
        context.final_answer = str(output["answer"])
        context.provenance_map = output.get("provenance_map", {})
        context.route_state["synthesis_complete"] = True
        return output

    def _fallback_answer(self, context: SharedContext) -> str:
        for step in reversed(context.history):
            if step.agent_id == "rag_agent" and isinstance(step.output, dict):
                return str(step.output.get("answer") or "No final answer was produced.")
        return "No final answer was produced."

    def _collect_citations(self, context: SharedContext) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []
        for result in context.tool_results.values():
            if isinstance(result, dict):
                citations.extend(result.get("citations", []))
        return citations
