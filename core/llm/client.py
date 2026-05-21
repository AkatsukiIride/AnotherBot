import json
from typing import AsyncGenerator

import httpx

from core.llm import ProviderConfig


class LLMClient:
    """Unified LLM API client"""

    def __init__(self):
        self.last_reasoning = ""
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._http = httpx.AsyncClient(
            timeout=120.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def close(self):
        await self._http.aclose()

    async def chat_stream(
        self, messages: list[dict], provider: ProviderConfig
    ) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": provider.model,
            "messages": messages,
            "temperature": provider.temperature,
            "max_tokens": provider.max_tokens,
            "stream": True,
        }
        reasoning_parts = []
        self.last_reasoning = ""
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        async with self._http.stream(
            "POST", f"{provider.base_url}/chat/completions",
            headers=headers, json=body
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        self.last_reasoning = "".join(reasoning_parts)
                        return
                    try:
                        data = json.loads(data_str)
                        if "usage" in data and data["usage"] is not None:
                            u = data["usage"]
                            self.last_usage = {
                                "prompt_tokens": u.get("prompt_tokens", 0),
                                "completion_tokens": u.get("completion_tokens", 0),
                                "total_tokens": u.get("total_tokens", 0),
                            }
                        delta = data["choices"][0].get("delta", {})
                        reasoning = delta.get("reasoning_content", "")
                        if reasoning:
                            reasoning_parts.append(reasoning)
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def chat(self, messages: list[dict], provider: ProviderConfig) -> str:
        full = []
        async for token in self.chat_stream(messages, provider):
            full.append(token)
        return "".join(full)

    async def test_connection(self, provider: ProviderConfig) -> dict:
        import time
        start = time.time()
        try:
            response = await self.chat(
                [{"role": "user", "content": "Hi"}], provider
            )
            latency = int((time.time() - start) * 1000)
            return {"success": True, "latency_ms": latency}
        except Exception as e:
            return {"success": False, "error": str(e)}
