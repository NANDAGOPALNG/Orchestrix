from typing import Any, Dict, List

from app.core.llm import OllamaClient
from app.schemas.shared_context import SharedContext, ToolResult
from app.tools.search import SearchTool


class MultiHopRAGAgent:
    """Performs at least two search-and-reasoning hops with citations."""

    def __init__(self, model: str):
        self.llm = OllamaClient(model)
        self.search = SearchTool()

    async def process(self, context: SharedContext) -> Dict[str, Any]:
        hop_queries = await self._plan_hops(context)
        hop_results: List[ToolResult] = []
        for query in hop_queries[:3]:
            result = await self.search.run(query)
            hop_results.append(result)
            context.tool_results[f"search:{len(context.tool_results)}"] = result.model_dump(mode="json")

        evidence = "\n\n".join(self._format_result(index, result) for index, result in enumerate(hop_results))
        prompt = f"""
Use the evidence to answer the user query. You must connect evidence across at least two hops.
In this project, SSE refers to Server-Sent Events for HTTP streaming via sse-starlette unless the
user explicitly asks about CPU instructions.
Return JSON with keys: claims, answer, citations.

User query:
{context.original_query}

Evidence:
{evidence}
"""
        fallback = {
            "claims": [
                {
                    "text": "Search evidence was limited; the answer is based on available context.",
                    "citations": [],
                }
            ],
            "answer": "I could not retrieve enough external evidence after retries, so the answer should be treated as provisional.",
            "citations": [],
        }
        response = await self.llm.generate_json(prompt, fallback=fallback)
        if not response.get("answer"):
            response = fallback
        response["hop_queries"] = hop_queries
        response["tool_results"] = [result.model_dump(mode="json") for result in hop_results]
        context.route_state["rag_complete"] = True
        return response

    async def _plan_hops(self, context: SharedContext) -> List[str]:
        prompt = f"""
Create 2 or 3 search queries for multi-hop reasoning.
If the query mentions SSE and this system, interpret SSE as Server-Sent Events.
Return JSON: {{"queries": ["first hop", "second hop"]}}
Question: {context.original_query}
"""
        data = await self.llm.generate_json(
            prompt,
            fallback={"queries": [context.original_query, f"background facts for {context.original_query}"]},
        )
        queries = [str(item) for item in data.get("queries", []) if str(item).strip()]
        while len(queries) < 2:
            queries.append(f"evidence related to {context.original_query}")
        return queries

    def _format_result(self, index: int, result: ToolResult) -> str:
        if not result.ok:
            return f"Hop {index + 1}: fallback={result.data}"
        snippets = []
        for item_index, item in enumerate(result.data or []):
            snippets.append(
                f"[hop{index + 1}:{item_index}] {item.get('title')}: {item.get('snippet')} ({item.get('url')})"
            )
        return "\n".join(snippets)
