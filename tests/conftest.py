import json
from pathlib import Path

import pytest

from app.config import Settings
from app.llm import LLMResponse, ToolCall

ROOT = Path(__file__).resolve().parent.parent


class FakeLLM:
    """Scripted model: returns queued responses per agent (matched by system prompt)."""

    def __init__(self, script: dict[str, list[LLMResponse]]):
        self.script = script
        self.calls: list[tuple[str, list[dict]]] = []

    def resolve(self, model: str) -> str:
        return "ollama/fake" if model == "local" else model

    async def chat(self, model, messages, tools=None):
        system = messages[0]["content"]
        self.calls.append((model, messages))
        for key, queue in self.script.items():
            if key in system and queue:
                return queue.pop(0)
        return LLMResponse(content="(no script)")


def call(name: str, **args) -> ToolCall:
    return ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(args))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        agents_file=ROOT / "agents.yaml",
        workspace_dir=tmp_path / "workspace",
        db_path=tmp_path / "test.db",
    )
