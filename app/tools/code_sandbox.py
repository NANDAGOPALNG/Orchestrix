import contextlib
import io
from typing import Any, Dict

from app.tools.base import RetryingTool


class PythonTool(RetryingTool):
    """Runs small Python snippets in a constrained namespace."""

    tool_name = "python"

    async def run(self, code: str) -> Any:
        async def operation() -> Dict[str, Any]:
            blocked = ("import os", "import sys", "subprocess", "socket", "open(", "__import__")
            if any(term in code for term in blocked):
                raise ValueError("code uses blocked operations")

            stdout = io.StringIO()
            namespace: Dict[str, Any] = {
                "__builtins__": {
                    "abs": abs,
                    "all": all,
                    "any": any,
                    "bool": bool,
                    "dict": dict,
                    "enumerate": enumerate,
                    "float": float,
                    "int": int,
                    "len": len,
                    "list": list,
                    "max": max,
                    "min": min,
                    "pow": pow,
                    "print": print,
                    "range": range,
                    "round": round,
                    "set": set,
                    "sorted": sorted,
                    "str": str,
                    "sum": sum,
                    "tuple": tuple,
                }
            }
            with contextlib.redirect_stdout(stdout):
                exec(code, namespace, namespace)
            return {
                "stdout": stdout.getvalue(),
                "locals": {
                    key: value
                    for key, value in namespace.items()
                    if not key.startswith("__") and isinstance(value, (str, int, float, bool, list, dict, tuple))
                },
            }

        async def fallback(error: str, attempts: int) -> Dict[str, Any]:
            return {
                "message": "Python sandbox failed after retries.",
                "last_error": error,
                "attempts": attempts,
                "code_preview": code[:400],
            }

        return await self._run_with_retries(operation, fallback)
