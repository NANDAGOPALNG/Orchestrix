import asyncio
from typing import Any, Awaitable, Callable

from app.schemas.shared_context import ToolResult


class RetryingTool:
    """Base class for tools with explicit two-retry fallback contracts."""

    tool_name: str = "tool"
    max_retries: int = 2

    async def _run_with_retries(
        self,
        operation: Callable[[], Awaitable[Any]],
        fallback: Callable[[str, int], Awaitable[Any]],
    ) -> ToolResult:
        last_error = ""
        for attempt in range(1, self.max_retries + 2):
            try:
                data = await operation()
                return ToolResult(
                    tool_name=self.tool_name,
                    ok=True,
                    data=data,
                    attempts=attempt,
                    fallback_used=False,
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt <= self.max_retries:
                    await asyncio.sleep(0.2 * attempt)

        fallback_data = await fallback(last_error, self.max_retries + 1)
        return ToolResult(
            tool_name=self.tool_name,
            ok=False,
            data=fallback_data,
            error=last_error,
            attempts=self.max_retries + 1,
            fallback_used=True,
        )
