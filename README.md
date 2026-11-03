# Agent Team

A local, multi-model AI agent backend. You talk to one **Chief** agent; it splits your request into tasks and hands them to a team of specialists. Each specialist can run on a different model: local through **Ollama**, or in the cloud through **OpenRouter**.

```
            you
             │
         ┌───▼───┐   delegate / delegate_parallel
         │ Chief │──────────────┬──────────┬───────────┬──────────┐
         └───────┘              ▼          ▼           ▼          ▼
                             coder    researcher   marketer   analyst   reviewer
                               │          │           │          │          │
                           workspace   web search  workspace   (local)   (local)
```

- **Multi-model**: every agent picks its own model in `agents.yaml`. You can mix Claude, DeepSeek, Gemini, Qwen and local models.
- **Works offline**: without an OpenRouter key, every agent falls back to your local Ollama model.
- **Parallel work**: the Chief can run independent tasks at the same time.
- **Tools**: a sandboxed shared workspace (read/write/list files), web search and URL fetch.
- **Memory**: sessions and team activity are stored in SQLite.
- **Live UI**: a chat page at `/` with a live feed of what each agent is doing.

## Quick start (Windows)

```bash
winget install astral-sh.uv
```

```bash
uv sync
```

```bash
copy .env.example .env
```

Edit `.env`: set `LOCAL_MODEL` to a model from `ollama list`, and optionally add `OPENROUTER_API_KEY`.

```bash
uv run uvicorn app.main:create_app --factory --reload --port 8000
```

Open http://localhost:8000.

## Choosing local models

Agents send long prompts plus tool definitions, so the local model needs:

- **Enough RAM/VRAM.** A model must fit in memory, with room to spare. On a 16 GB laptop without a dedicated GPU, use a 4B–8B model (`qwen3:4b`, `qwen3:8b`). Larger models swap to disk and slow to a crawl.
- **Tool-calling support.** Qwen3, Llama 3.1+ and Mistral models work.
- **A bigger context window.** Ollama defaults to 4096 tokens, which truncates agent prompts. Set `OLLAMA_CONTEXT_LENGTH=16384` as a system environment variable and restart Ollama.

A practical mix: run the Chief and the heavy specialists on OpenRouter, and keep the analyst and reviewer on a small local model.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat` | `{message, session_id?}` → final reply + all team events |
| POST | `/api/chat/stream` | Same, as server-sent events (live) |
| GET | `/api/agents` | Team roster with the resolved model for each agent |
| GET | `/api/sessions` · `/api/sessions/{id}` | Conversation history |
| GET | `/api/health` | Ollama reachable? OpenRouter key set? |

Interactive docs: http://localhost:8000/docs

## Customizing the team

Edit `agents.yaml`. Adding an agent is a few lines; the Chief learns about it automatically:

```yaml
  - name: designer
    title: UI/UX Designer
    model: openrouter/anthropic/claude-sonnet-5.5
    tools: [write_file, read_file]
    prompt: |
      You design clean, modern interfaces...
```

Model strings: `local`, `ollama/<model>`, `openrouter/<vendor>/<model>`.

To add a tool, write an async function in `app/tools.py`, register it in `build_tools`, and list it under an agent's `tools`.

## Development

```bash
uv run pytest
```

```bash
uv run ruff check .
```

GitHub Actions runs both on every push and pull request (`.github/workflows/ci.yml`).

## Project layout

```
app/
  main.py      FastAPI app and routes
  agents.py    agent tool-loop, Chief and Team
  llm.py       model router (Ollama + OpenRouter, fallback, concurrency limits)
  tools.py     workspace, web search, fetch
  memory.py    SQLite sessions
  config.py    settings (.env) and agents.yaml loader
  static/      chat UI
agents.yaml    the team
```

## Roadmap ideas

- Code execution sandbox (Docker) for the coder
- Long-term memory and RAG across sessions
- Specialists that can ask each other questions
- GitHub tool: agents open issues and PRs
- Auth for exposing the API beyond localhost
