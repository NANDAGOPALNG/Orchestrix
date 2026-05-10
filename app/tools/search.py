from typing import Any, Dict, List

import httpx

from app.tools.base import RetryingTool


class SearchTool(RetryingTool):
    """Search tool with retry and deterministic degraded fallback."""

    tool_name = "search"

    async def run(self, query: str) -> Any:
        async def operation() -> List[Dict[str, str]]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1},
                )
                response.raise_for_status()
                payload = response.json()

            results: List[Dict[str, str]] = []
            abstract = payload.get("AbstractText")
            if abstract:
                results.append(
                    {
                        "title": payload.get("Heading") or query,
                        "url": payload.get("AbstractURL") or "",
                        "snippet": abstract,
                    }
                )
            for topic in payload.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(
                        {
                            "title": topic.get("FirstURL", query),
                            "url": topic.get("FirstURL", ""),
                            "snippet": topic["Text"],
                        }
                    )
            if not results:
                raise RuntimeError("search returned no usable results")
            return results

        async def fallback(error: str, attempts: int) -> Dict[str, Any]:
            return {
                "message": "Search unavailable after retries; proceeding with model and context only.",
                "query": query,
                "last_error": error,
                "attempts": attempts,
            }

        result = await self._run_with_retries(operation, fallback)
        if result.ok and isinstance(result.data, list):
            result.citations = [
                {"source_id": f"search:{index}", "url": item.get("url"), "title": item.get("title")}
                for index, item in enumerate(result.data)
            ]
        return result
