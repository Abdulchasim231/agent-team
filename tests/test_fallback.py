import httpx
import pytest
from openai import APIStatusError

from app.config import Settings
from app.llm import AllModelsFailed, LLMResponse, ModelRouter


def status_error(code: int, headers: dict | None = None) -> APIStatusError:
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    return APIStatusError(f"error {code}", response=httpx.Response(code, request=req,
                                                                      headers=headers), body=None)


class ScriptedRouter(ModelRouter):
    """Real fallback logic; the network call is replaced by a per-model script."""

    def __init__(self, settings, outcomes: dict):
        super().__init__(settings)
        self.outcomes = outcomes
        self.tried: list[str] = []

    async def _chat_one(self, full, messages, tools):
        self.tried.append(full)
        outcome = self.outcomes[full]
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResponse(content=outcome, model=full)


def keys(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


CHAIN = ["groq/a", "gemini/b", "openrouter/c"]


def test_providers_without_keys_are_skipped():
    router = ModelRouter(keys(gemini_api_key="g", openrouter_api_key="o"))
    assert router.candidates(CHAIN) == ["gemini/b", "openrouter/c"]
    assert router.resolve(CHAIN) == "gemini/b"


def test_no_keys_at_all_falls_back_to_local():
    router = ModelRouter(keys(local_model="qwen3:8b"))
    assert router.candidates(CHAIN) == ["ollama/qwen3:8b"]


async def test_rate_limit_moves_to_next_model_and_cools_down():
    router = ScriptedRouter(keys(groq_api_key="x", gemini_api_key="y"),
                            {"groq/a": status_error(429), "gemini/b": "from gemini"})
    resp = await router.chat(CHAIN, [])
    assert resp.content == "from gemini" and resp.model == "gemini/b"

    # Second call skips the cooling-down model and goes straight to the next.
    router.tried.clear()
    await router.chat(CHAIN, [])
    assert router.tried == ["gemini/b"]
    assert router.resolve(CHAIN) == "gemini/b"


async def test_retry_after_header_sets_cooldown():
    router = ScriptedRouter(keys(groq_api_key="x", gemini_api_key="y"),
                            {"groq/a": status_error(429, {"retry-after": "120"}), "gemini/b": "ok"})
    await router.chat(CHAIN, [])
    import time
    assert 100 < router._cooldown["groq/a"] - time.monotonic() <= 120


async def test_all_failing_raises_with_every_reason():
    router = ScriptedRouter(keys(groq_api_key="x", gemini_api_key="y"),
                            {"groq/a": status_error(429), "gemini/b": status_error(404)})
    with pytest.raises(AllModelsFailed) as exc:
        await router.chat(CHAIN, [])
    assert len(exc.value.errors) == 2 and "404" in exc.value.errors[1]


async def test_auth_errors_are_not_hidden_by_fallback():
    router = ScriptedRouter(keys(groq_api_key="bad", gemini_api_key="y"),
                            {"groq/a": status_error(401), "gemini/b": "ok"})
    with pytest.raises(APIStatusError):
        await router.chat(CHAIN, [])
