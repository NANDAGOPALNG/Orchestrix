from typing import Any, Dict

from sqlalchemy import text
from sqlmodel import Session

from app.db.sessions import engine
from app.tools.base import RetryingTool


class SQLTool(RetryingTool):
    """Read-only SQL lookup tool."""

    tool_name = "sql"

    async def run(self, query: str) -> Any:
        async def operation() -> Dict[str, Any]:
            normalized = query.strip().lower()
            if not normalized.startswith("select"):
                raise ValueError("only SELECT statements are allowed")
            with Session(engine) as session:
                rows = session.execute(text(query)).mappings().all()
                return {"rows": [dict(row) for row in rows], "row_count": len(rows)}

        async def fallback(error: str, attempts: int) -> Dict[str, Any]:
            return {
                "message": "SQL lookup unavailable after retries.",
                "last_error": error,
                "attempts": attempts,
                "query": query,
            }

        return await self._run_with_retries(operation, fallback)
