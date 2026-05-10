from typing import Any, Dict

from app.core.llm import OllamaClient
from app.tools.base import RetryingTool


class SelfReflectionTool(RetryingTool):
    """LLM-backed reflection with a heuristic fallback."""

    tool_name = "self_reflection"

    def __init__(self, model: str):
        self.llm = OllamaClient(model)

    async def run(self, content: str, objective: str) -> Any:
        async def operation() -> Dict[str, Any]:
            prompt = f"""
Assess whether the answer satisfies the objective.

Objective:
{objective}

Answer:
{content}

Return JSON with keys: pass, confidence, issues, suggested_fix.
"""
            return await self.llm.generate_json(
                prompt,
                fallback={"pass": False, "confidence": 0.2, "issues": ["reflection unavailable"]},
            )

        async def fallback(error: str, attempts: int) -> Dict[str, Any]:
            has_citation = "[" in content and "]" in content
            return {
                "pass": bool(content.strip()) and len(content.split()) > 20,
                "confidence": 0.45 if has_citation else 0.3,
                "issues": [f"LLM reflection failed after {attempts} attempts: {error}"],
                "suggested_fix": "Add citations and explicit uncertainty where evidence is weak.",
            }

        return await self._run_with_retries(operation, fallback)
