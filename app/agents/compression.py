from typing import Any, Dict

from app.core.llm import OllamaClient
from app.schemas.shared_context import AgentStep, SharedContext


class CompressionAgent:
    """Lossily summarizes chat history while preserving tool data untouched."""

    def __init__(self, model: str):
        self.llm = OllamaClient(model)

    async def process(self, context: SharedContext) -> Dict[str, Any]:
        history_payload = [step.model_dump(mode="json") for step in context.history]
        prompt = f"""
Summarize the agent chat history for continued reasoning.
Keep user intent, decisions, open risks, and conclusions. Do not summarize tool_results.
Return JSON: {{"summary": "...", "retained_steps": ["agent_id: key contribution"]}}

History:
{history_payload}
"""
        fallback = {
            "summary": "Compressed prior agent history. Tool results remain available losslessly in SharedContext.tool_results.",
            "retained_steps": [f"{step.agent_id}: {step.action}" for step in context.history[-5:]],
        }
        compressed = await self.llm.generate_json(prompt, fallback=fallback)
        if not compressed.get("summary"):
            compressed = fallback
        context.compressed_summary = str(compressed["summary"])
        context.compression_events.append(compressed)
        context.history = [
            AgentStep(
                agent_id="compression_agent",
                thought="Context budget exceeded; compressed chat history and retained tool data losslessly.",
                action="compress_history",
                output=compressed,
                tokens_used=0,
            )
        ]
        context.total_tokens = 0
        context.route_state["compressed"] = True
        return compressed
