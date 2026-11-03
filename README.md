# Agent Team

A local, multi-model AI agent backend. You talk to one **Chief** agent; it splits your request into tasks and hands them to a team of specialists. Each specialist can run on a different model: local through **Ollama**, or in the cloud through **Groq, Gemini, Cerebras, Mistral, GitHub Models or OpenRouter**.

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
- **Runs on free tiers**: each agent has a fallback chain across providers. When one hits its rate limit, the agent switches to the next and skips the limited model for a while.
- **Works offline**: with no cloud keys, every agent falls back to your local Ollama model.
- **Live office**: the dashboard shows every agent as a pixel character at its desk, with what it is working on right now.
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

Edit `.env`: add keys for the free providers you want (links are in the file) and set `LOCAL_MODEL` to a model from `ollama list`.

```bash
uv run uvicorn app.main:create_app --factory --reload --port 8000
```

Open http://localhost:8000.

## Free providers and fallback chains

| Provider | Get a key | Notes |
|---|---|---|
| Groq | console.groq.com/keys | Fast; the most generous free tier |
| Gemini | aistudio.google.com/apikey | Flash models are free |
| Cerebras | cloud.cerebras.ai | Very fast; smaller context on free tier |
| Mistral | console.mistral.ai | Free "Experiment" plan; Codestral for code |
| GitHub Models | github.com/settings/tokens | Fine-grained token with "Models: read" |
| OpenRouter | openrouter.ai/keys | `:free` models without credits |

Free limits change often; check each provider's dashboard. In `agents.yaml`, give an agent a list of models and the router tries them in order:

```yaml
    model:
      - groq/openai/gpt-oss-120b
      - gemini/gemini-flash-latest
      - openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
```

Providers without a key are skipped. On a rate limit, missing credits, an unknown model, a timeout or a server error, the next model is tried. Rate-limited models are skipped for `RATE_LIMIT_COOLDOWN` seconds, or for as long as the provider's `Retry-After` header says. To list the model IDs a provider offers: `GET /api/providers/groq/models`.

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
