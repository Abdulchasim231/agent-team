"""The agent loop and the team (chief + specialists)."""

import asyncio
import json
from collections.abc import Awaitable, Callable

from app.config import AgentSpec, Settings, TeamConfig
from app.llm import ChatModel, ToolCall
from app.tools import Tool

Emit = Callable[[dict], Awaitable[None]]


async def _noop(_: dict) -> None:
    pass


class Agent:
    def __init__(
        self,
        spec: AgentSpec,
        llm: ChatModel,
        tools: dict[str, Tool],
        max_steps: int = 10,
        emit: Emit = _noop,
    ):
        self.spec = spec
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.emit = emit

    async def _call_tool(self, call: ToolCall) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            return f"Error: unknown tool '{call.name}'."
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as e:
            return f"Error: invalid JSON arguments: {e}"
        await self.emit({"type": "tool", "agent": self.spec.name, "tool": call.name, "args": args})
        try:
            return await tool.fn(**args)
        except Exception as e:  # tool errors go back to the model, not up the stack
            return f"Error running {call.name}: {type(e).__name__}: {e}"

    async def run(self, task: str, history: list[dict] | None = None) -> str:
        messages = [
            {"role": "system", "content": self.spec.prompt},
            *(history or []),
            {"role": "user", "content": task},
        ]
        schemas = [t.schema() for t in self.tools.values()] or None
        for _ in range(self.max_steps):
            resp = await self.llm.chat(self.spec.model, messages, schemas)
            if not resp.tool_calls:
                return resp.content
            if resp.content:
                await self.emit({"type": "thought", "agent": self.spec.name, "text": resp.content})
            messages.append({
                "role": "assistant",
                "content": resp.content or None,
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": c.arguments}}
                    for c in resp.tool_calls
                ],
            })
            results = await asyncio.gather(*(self._call_tool(c) for c in resp.tool_calls))
            for call, result in zip(resp.tool_calls, results, strict=True):
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        messages.append({
            "role": "user",
            "content": "Step limit reached. Summarize what you did and the result now.",
        })
        return (await self.llm.chat(self.spec.model, messages)).content


class Team:
    def __init__(self, config: TeamConfig, llm: ChatModel, tools: dict[str, Tool],
                 settings: Settings):
        self.config = config
        self.llm = llm
        self.tools = tools
        self.settings = settings

    def roster(self) -> list[dict]:
        specs = [self.config.chief, *self.config.specialists]
        return [
            {"name": s.name, "title": s.title, "model": s.model,
             "resolved_model": self.llm.resolve(s.model), "tools": s.tools}
            for s in specs
        ]

    def _specialist(self, name: str, emit: Emit) -> Agent:
        spec = self.config.specialist(name)
        if spec is None:
            raise KeyError(name)
        tools = {n: self.tools[n] for n in spec.tools if n in self.tools}
        return Agent(spec, self.llm, tools, self.settings.max_agent_steps, emit)

    async def _delegate(self, agent: str, task: str, emit: Emit) -> str:
        if self.config.specialist(agent) is None:
            names = ", ".join(s.name for s in self.config.specialists)
            return f"Error: no specialist named '{agent}'. Available: {names}"
        await emit({"type": "delegate", "agent": agent, "task": task,
                    "model": self.llm.resolve(self.config.specialist(agent).model)})
        try:
            result = await self._specialist(agent, emit).run(task)
        except Exception as e:
            await emit({"type": "error", "agent": agent, "text": str(e)})
            return f"Error: {agent} failed: {type(e).__name__}: {e}"
        await emit({"type": "result", "agent": agent, "text": result})
        return result

    def _chief_tools(self, emit: Emit) -> dict[str, Tool]:
        names = [s.name for s in self.config.specialists]

        async def delegate(agent: str, task: str) -> str:
            return await self._delegate(agent, task, emit)

        async def delegate_parallel(assignments: list[dict]) -> str:
            results = await asyncio.gather(
                *(self._delegate(a.get("agent", ""), a.get("task", ""), emit)
                  for a in assignments)
            )
            return "\n\n".join(
                f"### {a.get('agent')}\n{r}" for a, r in zip(assignments, results, strict=True)
            )

        assignment = {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": names},
                "task": {"type": "string", "description": "Complete, self-contained brief"},
            },
            "required": ["agent", "task"],
        }
        tools = [
            Tool("delegate", "Assign one task to a specialist and wait for the result.",
                 assignment, delegate),
            Tool("delegate_parallel",
                 "Assign several independent tasks to specialists at once; they work in parallel.",
                 {"type": "object",
                  "properties": {"assignments": {"type": "array", "items": assignment}},
                  "required": ["assignments"]},
                 delegate_parallel),
        ]
        return {t.name: t for t in tools}

    def _chief_prompt(self) -> str:
        roster = "\n".join(
            f"- {s.name} ({s.title}): tools = {', '.join(s.tools) or 'none'}"
            for s in self.config.specialists
        )
        return f"{self.config.chief.prompt}\n\nYour team:\n{roster}"

    async def run(self, message: str, history: list[dict] | None = None,
                  emit: Emit = _noop) -> str:
        chief_spec = AgentSpec(
            name=self.config.chief.name,
            title=self.config.chief.title,
            model=self.config.chief.model,
            prompt=self._chief_prompt(),
        )
        chief = Agent(chief_spec, self.llm, self._chief_tools(emit),
                      self.settings.max_agent_steps, emit)
        return await chief.run(message, history)
