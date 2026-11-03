"""Model router: one interface for local (Ollama) and cloud (OpenRouter) models.

Both providers speak the OpenAI chat-completions protocol, so a single client type
covers them; only base URL, key and concurrency differ.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from openai import AsyncOpenAI

from app.config import Settings

OPENROUTER_URL = "https://openrouter.ai/api/v1"
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, as returned by the model


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""


class ChatModel(Protocol):
    def resolve(self, model: str) -> str: ...

    async def chat(
        self, model: str, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse: ...


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[str, AsyncOpenAI] = {}
        self._limits = {
            "ollama": asyncio.Semaphore(settings.ollama_concurrency),
            "openrouter": asyncio.Semaphore(settings.openrouter_concurrency),
        }

    def resolve(self, model: str) -> str:
        """Map a config model string to a concrete 'provider/name', applying fallbacks."""
        if model == "local":
            return f"ollama/{self.settings.local_model}"
        provider, _, name = model.partition("/")
        if provider not in self._limits or not name:
            raise ValueError(f"Unknown model '{model}'. Use local, ollama/... or openrouter/...")
        if provider == "openrouter" and not self.settings.openrouter_api_key:
            return f"ollama/{self.settings.local_model}"
        return model

    def _client(self, provider: str) -> AsyncOpenAI:
        if provider not in self._clients:
            if provider == "ollama":
                self._clients[provider] = AsyncOpenAI(
                    base_url=f"{self.settings.ollama_base_url.rstrip('/')}/v1",
                    api_key="ollama",
                    timeout=self.settings.request_timeout,
                )
            else:
                self._clients[provider] = AsyncOpenAI(
                    base_url=OPENROUTER_URL,
                    api_key=self.settings.openrouter_api_key,
                    timeout=self.settings.request_timeout,
                    default_headers={"X-Title": "Agent Team"},
                )
        return self._clients[provider]

    async def chat(
        self, model: str, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        resolved = self.resolve(model)
        provider, _, name = resolved.partition("/")
        kwargs: dict = {"model": name, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        async with self._limits[provider]:
            resp = await self._client(provider).chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (msg.tool_calls or [])
        ]
        content = _THINK_RE.sub("", msg.content or "").strip()
        return LLMResponse(content=content, tool_calls=calls, model=resolved)

    async def health(self) -> dict:
        status = {"openrouter_key": bool(self.settings.openrouter_api_key), "ollama": False}
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.settings.ollama_base_url.rstrip('/')}/api/tags")
                r.raise_for_status()
                status["ollama"] = True
                status["ollama_models"] = [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError:
            pass
        return status
