import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIError
from pydantic import BaseModel

from app.agents import Team
from app.config import Settings, load_team
from app.events import EventHub
from app.llm import AllModelsFailed, ChatModel, ModelRouter
from app.memory import Memory
from app.tools import Workspace, build_tools

STATIC = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def create_app(settings: Settings | None = None, llm: ChatModel | None = None) -> FastAPI:
    settings = settings or Settings()
    llm = llm or ModelRouter(settings)
    team = Team(load_team(settings.agents_file), llm,
                build_tools(Workspace(settings.workspace_dir)), settings)
    memory = Memory(settings.db_path)
    hub = EventHub()

    app = FastAPI(title="Agent Team", version="0.1.0")
    app.state.hub = hub
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(APIError)
    async def model_error(_: Request, exc: APIError):
        # Provider problems (no credits, bad key, model down) are not server bugs.
        status = getattr(exc, "status_code", None) or 502
        return JSONResponse({"error": "model_provider", "detail": exc.message}, status_code=status)

    @app.exception_handler(AllModelsFailed)
    async def all_models_failed(_: Request, exc: AllModelsFailed):
        return JSONResponse({"error": "all_models_failed", "detail": exc.errors}, status_code=503)

    def _session(req: ChatRequest) -> str:
        if req.session_id:
            if not memory.session_exists(req.session_id):
                raise HTTPException(404, "Session not found")
            return req.session_id
        return memory.create_session(req.message)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    async def health():
        if isinstance(llm, ModelRouter):
            return {"ok": True, **(await llm.health())}
        return {"ok": True}

    @app.get("/api/providers/{provider}/models")
    async def provider_models(provider: str):
        """Model IDs a configured provider offers right now (to build chains in agents.yaml)."""
        if not isinstance(llm, ModelRouter):
            return []
        return await llm.list_models(provider)

    @app.get("/api/agents")
    async def agents():
        return team.roster()

    @app.get("/api/sessions")
    async def sessions():
        return memory.list_sessions()

    @app.get("/api/sessions/{sid}")
    async def session(sid: str):
        if not memory.session_exists(sid):
            raise HTTPException(404, "Session not found")
        return {"id": sid, "messages": memory.messages(sid)}

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str):
        memory.delete_session(sid)
        return {"ok": True}

    @app.get("/api/events")
    async def events_stream(request: Request):
        """Server-sent events: everything every agent does, across all requests."""
        async def stream():
            with hub.subscribe() as queue:
                yield _sse(hub.snapshot())
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield _sse(event)

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def run_turn(sid: str, message: str, history: list[dict], emit) -> str:
        """Run one chat turn, persist it and broadcast it to the office view."""
        events: list[dict] = []

        async def tee(e: dict) -> None:
            events.append(e)
            hub.publish(e)
            await emit(e)

        hub.publish({"type": "start", "agent": "chief", "text": message})
        try:
            reply = await team.run(message, history, tee)
        except Exception as e:
            hub.publish({"type": "error", "agent": "chief", "text": str(e)})
            raise
        memory.add_message(sid, "assistant", reply, events)
        hub.publish({"type": "reply", "agent": "chief", "text": reply})
        return reply

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        """Blocking: returns the chief's final reply plus everything the team did."""
        sid = _session(req)
        history = memory.history(sid)
        events: list[dict] = []

        async def emit(e: dict) -> None:
            events.append(e)

        memory.add_message(sid, "user", req.message)
        reply = await run_turn(sid, req.message, history, emit)
        return {"session_id": sid, "reply": reply, "events": events}

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest):
        """Server-sent events: live team activity, then a final 'reply' event."""
        sid = _session(req)
        history = memory.history(sid)
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def work():
            try:
                reply = await run_turn(sid, req.message, history, queue.put)
                await queue.put({"type": "reply", "agent": "chief", "text": reply})
            except Exception as e:
                await queue.put({"type": "error", "agent": "chief", "text": str(e)})
            finally:
                await queue.put(None)

        async def stream():
            yield _sse({"type": "session", "session_id": sid})
            task = asyncio.create_task(work())
            try:
                while (event := await queue.get()) is not None:
                    yield _sse(event)
            finally:
                if not task.done():
                    task.cancel()

        memory.add_message(sid, "user", req.message)
        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
