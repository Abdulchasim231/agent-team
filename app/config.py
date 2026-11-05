from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Cloud providers. Any left empty are skipped in model chains.
    openrouter_api_key: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""
    cerebras_api_key: str = ""
    mistral_api_key: str = ""
    github_token: str = ""

    ollama_base_url: str = "http://localhost:11434"
    local_model: str = "qwen3:8b"
    # Max concurrent requests per provider. Local models are slow in parallel.
    ollama_concurrency: int = 1
    openrouter_concurrency: int = 8
    # Seconds to skip a model after it hits a rate limit (unless it sends Retry-After).
    rate_limit_cooldown: float = 60.0
    # When every model in a chain is rate limited, wait at most this long and retry once.
    max_rate_limit_wait: float = 30.0

    agents_file: Path = Path("agents.yaml")
    workspace_dir: Path = Path("workspace")
    db_path: Path = Path("data/agent_team.db")

    max_agent_steps: int = 10
    # Per model call. A stuck free model times out and the next one in the chain is tried.
    request_timeout: float = 120.0


@dataclass
class AgentSpec:
    name: str
    title: str
    model: str | list[str]  # one model, or a fallback chain tried in order
    prompt: str
    tools: list[str] = field(default_factory=list)


@dataclass
class TeamConfig:
    chief: AgentSpec
    specialists: list[AgentSpec]

    def specialist(self, name: str) -> AgentSpec | None:
        return next((s for s in self.specialists if s.name == name), None)


def _spec(raw: dict) -> AgentSpec:
    return AgentSpec(
        name=raw["name"],
        title=raw.get("title", raw["name"]),
        model=raw["model"],
        prompt=raw["prompt"].strip(),
        tools=list(raw.get("tools", [])),
    )


def load_team(path: Path) -> TeamConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    specialists = [_spec(s) for s in data.get("specialists", [])]
    names = [s.name for s in specialists]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate specialist names in {path}")
    return TeamConfig(chief=_spec(data["chief"]), specialists=specialists)
