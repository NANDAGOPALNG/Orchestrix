from typing import Any, Dict

from app.core.llm import OllamaClient
from app.schemas.shared_context import SharedContext


class DecompositionAgent:
    """Creates a task DAG and stores it in SharedContext."""

    def __init__(self, model: str):
        self.model = model
        self.llm = OllamaClient(model)

    async def process(self, context: SharedContext) -> Dict[str, Any]:
        prompt = f"""
Break the user query into a small task DAG for a multi-agent system.
Return ONLY JSON:
{{
  "tasks": [
    {{"id": "t1", "description": "...", "agent": "rag_agent", "depends_on": []}}
  ],
  "ambiguities": ["..."],
  "success_criteria": ["..."]
}}

User query: {context.original_query}
"""
        fallback = {
            "tasks": [
                {
                    "id": "t1",
                    "description": f"Research and answer: {context.original_query}",
                    "agent": "rag_agent",
                    "depends_on": [],
                },
                {
                    "id": "t2",
                    "description": "Critique answer claims and confidence.",
                    "agent": "critique_agent",
                    "depends_on": ["t1"],
                },
                {
                    "id": "t3",
                    "description": "Synthesize final response with provenance.",
                    "agent": "synthesis_agent",
                    "depends_on": ["t2"],
                },
            ],
            "ambiguities": [],
            "success_criteria": ["Answer is grounded, concise, and cites evidence when available."],
        }
        dag = await self.llm.generate_json(prompt, fallback=fallback)
        if not dag.get("tasks"):
            dag = fallback
        context.tasks = dag["tasks"]
        context.route_state["decomposed"] = True
        return dag
