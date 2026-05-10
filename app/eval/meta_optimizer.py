from typing import Any, Dict, List

from app.core.config import settings
from app.core.llm import OllamaClient


class MetaAgent:
    """Proposes prompt diffs from failed evaluation cases."""

    def __init__(self, model: str = settings.LLM_MODEL):
        self.llm = OllamaClient(model)

    async def propose_prompt_diffs(self, failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not failures:
            return []

        prompt = f"""
You improve a multi-agent orchestration system.
Given failed eval cases, propose minimal prompt diffs per agent.
Return JSON:
{{"diffs": [{{"agent_id": "...", "rationale": "...", "prompt_diff": "--- old\\n+++ new\\n..."}}]}}

Failures:
{failures}
"""
        fallback = {
            "diffs": [
                {
                    "agent_id": "synthesis_agent",
                    "rationale": "Fallback proposal: emphasize uncertainty, citations, and tool failure disclosure.",
                    "prompt_diff": "+ Always disclose missing evidence, failed tools, and residual uncertainty.",
                }
            ]
        }
        data = await self.llm.generate_json(prompt, fallback=fallback)
        return list(data.get("diffs", fallback["diffs"]))
