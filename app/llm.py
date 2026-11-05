"""Model router: one interface for local and cloud models, with automatic fallback.

Every supported provider speaks the OpenAI chat-completions protocol, so a single client
type covers them; only base URL, key and concurrency differ.

An agent's model can be a single string or a list. With a list, the router tries each
model in order and moves on when one is rate limited, out of credits, down or unknown.
Rate-limited models are skipped for a cool-down period, which spreads load across
several free tiers.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.config import Settings

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
# Statuses where another model may well succeed.
_FALLBACK_STATUSES = {402, 404, 408, 413, 429, 500, 502, 503, 504}
_COOLDOWN_STATUSES = {402, 429}


@dataclass(frozen=True)
class Provider:
    base_url: str
    key_setting: str  # Settings attribute holding the API key ("" for none needed)
    concurrency: int = 8


PROVIDERS = {
    "ollama": Provider("", "", 1),  # base URL and concurrency come from settings
    "openrouter": Provider("https://openrouter.ai/api/v1", "openrouter_api_key"),
    "groq": Provider("https://api.groq.com/openai/v1", "groq_api_key"),
    "gemini": Provider("https://generativelanguage.googleapis.com/v1beta/openai/",
                       "gemini_api_key"),
    "cerebras": Provider("https://api.cerebras.ai/v1", "cerebras_api_key"),
    "mistral": Provider("https://api.mistral.ai/v1", "mistral_api_key"),
    "github": Provider("https://models.github.ai/inference", "github_token"),
}


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


class AllModelsFailed(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("All models failed: " + " | ".join(errors))


ModelSpec = str | list[str]


def _bad_tool_call(err: APIStatusError) -> bool:
    msg = str(err.message).lower()
    return err.status_code == 400 and ("tool call validation" in msg or "tool_use_failed" in msg)


class ChatModel(Protocol):
    def resolve(self, model: ModelSpec) -> str: ...

    async def chat(
        self, model: ModelSpec, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse: ...


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[str, AsyncOpenAI] = {}
        self._limits = {
            name: asyncio.Semaphore(
                settings.ollama_concurrency if name == "ollama"
                else settings.openrouter_concurrency if name == "openrouter"
                else p.concurrency
            )
            for name, p in PROVIDERS.items()
        }
        self._cooldown: dict[str, float] = {}  # model -> monotonic time it may be retried

    def _key(self, provider: str) -> str:
        attr = PROVIDERS[provider].key_setting
        return getattr(self.settings, attr) if attr else "ollama"

    def available(self, provider: str) -> bool:
        return bool(self._key(provider))

    def _expand(self, model: str) -> str:
        if model == "local":
            return f"ollama/{self.settings.local_model}"
        provider, _, name = model.partition("/")
        if provider not in PROVIDERS or not name:
            known = ", ".join(PROVIDERS)
            raise ValueError(f"Unknown model '{model}'. Use local or <provider>/<model> ({known})")
        return model

    def candidates(self, model: ModelSpec) -> list[str]:
        """Concrete models to try, in order: configured, keyed providers only."""
        specs = [model] if isinstance(model, str) else list(model)
        out = []
        for spec in specs:
            full = self._expand(spec)
            if self.available(full.partition("/")[0]) and full not in out:
                out.append(full)
        return out or [f"ollama/{self.settings.local_model}"]

    def resolve(self, model: ModelSpec) -> str:
        """The model that would be tried first right now."""
        cands = self.candidates(model)
        now = time.monotonic()
        return next((c for c in cands if self._cooldown.get(c, 0) <= now), cands[0])

    def _client(self, provider: str) -> AsyncOpenAI:
        if provider not in self._clients:
            base = (f"{self.settings.ollama_base_url.rstrip('/')}/v1" if provider == "ollama"
                    else PROVIDERS[provider].base_url)
            headers = {"X-Title": "Agent Team"} if provider == "openrouter" else None
            self._clients[provider] = AsyncOpenAI(
                base_url=base, api_key=self._key(provider),
                timeout=self.settings.request_timeout, default_headers=headers,
            )
        return self._clients[provider]

    async def _chat_one(self, full: str, messages: list[dict], tools: list[dict] | None):
        provider, _, name = full.partition("/")
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
        return LLMResponse(content=content, tool_calls=calls, model=full)

    def _cool_down(self, full: str, err: APIStatusError) -> None:
        try:
            wait = float(err.response.headers.get("retry-after", ""))
        except ValueError:
            wait = self.settings.rate_limit_cooldown
        self._cooldown[full] = time.monotonic() + min(max(wait, 5), 3600)

    async def chat(
        self, model: ModelSpec, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        cands = self.candidates(model)
        errors: list[str] = []
        for round_ in range(2):
            now = time.monotonic()
            # Cooling-down models go last instead of being dropped: better a slow retry than none.
            ordered = sorted(cands, key=lambda c: self._cooldown.get(c, 0) > now)
            only_rate_limited = True
            for full in ordered:
                try:
                    return await self._chat_one_retrying(full, messages, tools)
                except APIStatusError as e:
                    if e.status_code not in _FALLBACK_STATUSES and not _bad_tool_call(e):
                        raise
                    if e.status_code in _COOLDOWN_STATUSES:
                        self._cool_down(full, e)
                    else:
                        only_rate_limited = False
                    errors.append(f"{full}: {e.status_code} {e.message}")
                except (APIConnectionError, APITimeoutError) as e:
                    only_rate_limited = False
                    errors.append(f"{full}: {type(e).__name__}")
            # Every model is merely rate limited: wait for the first to free up, then retry once.
            if round_ == 0 and only_rate_limited:
                wait = min(self._cooldown.get(c, 0) for c in cands) - time.monotonic()
                await asyncio.sleep(min(max(wait, 1), self.settings.max_rate_limit_wait))
                continue
            break
        raise AllModelsFailed(errors)

    async def _chat_one_retrying(self, full, messages, tools):
        # Some providers (Groq) reject a response in which the model called a tool it was not
        # given. Models are non-deterministic, so one more try usually works.
        try:
            return await self._chat_one(full, messages, tools)
        except APIStatusError as e:
            if not _bad_tool_call(e):
                raise
            return await self._chat_one(full, messages, tools)

    async def health(self) -> dict:
        status = {
            "providers": {p: self.available(p) for p in PROVIDERS if p != "ollama"},
            "openrouter_key": self.available("openrouter"),
            "ollama": False,
        }
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.settings.ollama_base_url.rstrip('/')}/api/tags")
                r.raise_for_status()
                status["ollama"] = True
                status["ollama_models"] = [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError:
            pass
        return status

    async def list_models(self, provider: str) -> list[str]:
        """Model IDs a provider currently offers, for picking chains in agents.yaml."""
        if provider not in PROVIDERS or not self.available(provider):
            return []
        page = await self._client(provider).models.list()
        return sorted(m.id for m in page.data)
