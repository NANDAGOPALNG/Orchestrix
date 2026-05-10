import json
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings


class OllamaClient:
    """Small async Ollama client with JSON parsing fallback."""

    def __init__(self, model: str = settings.LLM_MODEL):
        self.model = model
        self.generate_url = f"{settings.OLLAMA_BASE_URL}/api/generate"

    async def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.generate_url, json=payload)
            response.raise_for_status()
            return str(response.json().get("response", "")).strip()

    async def generate_json(
        self,
        prompt: str,
        *,
        fallback: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        try:
            raw = await self.generate(prompt, json_mode=True, timeout=timeout)
            return json.loads(raw)
        except Exception:
            return fallback or {}
