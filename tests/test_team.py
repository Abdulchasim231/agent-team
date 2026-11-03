from app.agents import Team
from app.config import load_team
from app.llm import LLMResponse
from app.tools import Workspace, build_tools
from tests.conftest import FakeLLM, call


def make_team(settings, llm):
    tools = build_tools(Workspace(settings.workspace_dir))
    return Team(load_team(settings.agents_file), llm, tools, settings)


async def test_chief_answers_directly(settings):
    llm = FakeLLM({"You are the Chief": [LLMResponse(content="Hi!")]})
    assert await make_team(settings, llm).run("hello") == "Hi!"


async def test_chief_delegates_and_specialist_uses_tools(settings):
    llm = FakeLLM({
        "You are the Chief": [
            LLMResponse(content="", tool_calls=[
                call("delegate", agent="coder", task="write hi.py")]),
            LLMResponse(content="Done: hi.py is in the workspace."),
        ],
        "senior software engineer": [
            LLMResponse(content="", tool_calls=[
                call("write_file", path="hi.py", content="print(1)")]),
            LLMResponse(content="Wrote hi.py"),
        ],
    })
    events = []

    async def emit(e):
        events.append(e)

    reply = await make_team(settings, llm).run("build hi", emit=emit)

    assert reply == "Done: hi.py is in the workspace."
    assert (settings.workspace_dir / "hi.py").read_text() == "print(1)"
    assert [e["type"] for e in events] == ["tool", "delegate", "tool", "result"]
    # The chief saw the specialist's result as a tool message.
    chief_last = [m for model, m in llm.calls if "Chief" in m[0]["content"]][-1]
    assert chief_last[-1] == {
        "role": "tool", "tool_call_id": "call_delegate", "content": "Wrote hi.py"}


async def test_parallel_delegation(settings):
    llm = FakeLLM({
        "You are the Chief": [
            LLMResponse(content="", tool_calls=[call("delegate_parallel", assignments=[
                {"agent": "researcher", "task": "a"}, {"agent": "marketer", "task": "b"}])]),
            LLMResponse(content="merged"),
        ],
        "research analyst": [LLMResponse(content="facts")],
        "marketing and content": [LLMResponse(content="copy")],
    })
    assert await make_team(settings, llm).run("go") == "merged"
    tool_msg = llm.calls[-1][1][-1]["content"]
    assert "### researcher\nfacts" in tool_msg and "### marketer\ncopy" in tool_msg


async def test_unknown_specialist_is_reported_to_chief(settings):
    llm = FakeLLM({
        "You are the Chief": [
            LLMResponse(content="", tool_calls=[call("delegate", agent="ghost", task="x")]),
            LLMResponse(content="ok"),
        ],
    })
    await make_team(settings, llm).run("go")
    assert "no specialist named 'ghost'" in llm.calls[-1][1][-1]["content"]


def test_roster_lists_everyone(settings):
    roster = make_team(settings, FakeLLM({})).roster()
    assert roster[0]["name"] == "chief"
    assert {"coder", "researcher", "marketer", "analyst", "reviewer"} <= {a["name"] for a in roster}
