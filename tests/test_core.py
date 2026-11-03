import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMResponse, ModelRouter
from app.main import create_app
from app.tools import Workspace, build_tools, html_to_text
from tests.conftest import FakeLLM


def test_router_falls_back_to_local_without_key():
    router = ModelRouter(Settings(_env_file=None, openrouter_api_key="", local_model="qwen3:8b"))
    assert router.resolve("openrouter/anthropic/claude-sonnet-5.5") == "ollama/qwen3:8b"
    assert router.resolve("local") == "ollama/qwen3:8b"
    assert router.resolve("ollama/llama3") == "ollama/llama3"


def test_router_uses_openrouter_with_key():
    router = ModelRouter(Settings(_env_file=None, openrouter_api_key="sk-test"))
    assert router.resolve("openrouter/x/y") == "openrouter/x/y"
    with pytest.raises(ValueError):
        router.resolve("gpt-4")


async def test_workspace_blocks_path_escape(tmp_path):
    tools = build_tools(Workspace(tmp_path / "ws"))
    assert "Wrote" in await tools["write_file"].fn(path="a/b.txt", content="hi")
    assert await tools["read_file"].fn(path="a/b.txt") == "hi"
    assert await tools["list_files"].fn() == "a/b.txt"
    with pytest.raises(PermissionError):
        await tools["read_file"].fn(path="../secret.txt")


def test_html_to_text():
    assert html_to_text("<p>Hello <b>you</b></p><script>x()</script>") == "Hello you"


def test_chat_api_persists_sessions(settings):
    llm = FakeLLM({"You are the Chief": [LLMResponse(content="one"), LLMResponse(content="two")]})
    client = TestClient(create_app(settings, llm))

    r = client.post("/api/chat", json={"message": "first"}).json()
    sid = r["session_id"]
    assert r["reply"] == "one"
    second = client.post("/api/chat", json={"message": "second", "session_id": sid}).json()
    assert second["reply"] == "two"

    # Second turn included the first turn as history.
    assert [m["content"] for m in llm.calls[-1][1][1:]] == ["first", "one", "second"]
    msgs = client.get(f"/api/sessions/{sid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert client.post("/api/chat", json={"message": "x", "session_id": "nope"}).status_code == 404


def test_provider_error_is_reported_not_500(settings):
    import httpx
    from openai import APIStatusError

    class BrokeLLM(FakeLLM):
        async def chat(self, model, messages, tools=None):
            req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            resp = httpx.Response(402, request=req)
            raise APIStatusError("Insufficient credits", response=resp, body=None)

    client = TestClient(create_app(settings, BrokeLLM({})))
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 402
    assert r.json()["detail"] == "Insufficient credits"


def test_chat_broadcasts_to_office_view(settings):
    llm = FakeLLM({"You are the Chief": [LLMResponse(content="hello")]})
    app = create_app(settings, llm)
    hub = app.state.hub
    with hub.subscribe() as queue:
        TestClient(app).post("/api/chat", json={"message": "hi"})
        seen = [queue.get_nowait()["type"] for _ in range(queue.qsize())]
    assert seen == ["start", "reply"]
    assert hub.latest["chief"]["text"] == "hello"
    assert hub.snapshot()["stats"]["requests"] == 1


def test_chat_stream_emits_reply(settings):
    llm = FakeLLM({"You are the Chief": [LLMResponse(content="streamed")]})
    client = TestClient(create_app(settings, llm))
    with client.stream("POST", "/api/chat/stream", json={"message": "hi"}) as r:
        body = "".join(r.iter_text())
    assert '"type": "session"' in body and '"text": "streamed"' in body
