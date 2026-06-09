"""Tests for llm.PauseChain and chain resume from message history."""

import asyncio
import json

import pytest

import llm
from llm.parts import Message, TextPart, ToolCallPart, ToolResultPart


# ---- PauseChain ----


def test_pause_chain_sync_model():
    after_calls = []

    def needs_input(path: str) -> str:
        raise llm.PauseChain("waiting for approval")

    def before(tool, tool_call):
        pass

    def after(tool, tool_call, tool_result):
        after_calls.append(tool_result.name)

    model = llm.get_model("echo")
    chain = model.chain(
        json.dumps(
            {"tool_calls": [{"name": "needs_input", "arguments": {"path": "/tmp"}}]}
        ),
        tools=[needs_input],
        before_call=before,
        after_call=after,
    )
    with pytest.raises(llm.PauseChain) as exc_info:
        chain.text()

    pause = exc_info.value
    assert str(pause) == "waiting for approval"
    assert pause.tool_call is not None
    assert pause.tool_call.name == "needs_input"
    assert pause.tool_call.arguments == {"path": "/tmp"}
    assert pause.tool_call.tool_call_id.startswith("tc_")
    assert pause.tool_results == []
    # after_call must not fire for the paused tool
    assert after_calls == []
    # The response that requested the tool call completed normally
    assert len(chain._responses) == 1


@pytest.mark.asyncio
async def test_pause_chain_async_model_siblings_complete():
    after_calls = []
    executed = []

    async def needs_input() -> str:
        raise llm.PauseChain("hold on")

    async def sibling() -> str:
        await asyncio.sleep(0.01)
        executed.append("sibling")
        return "done"

    async def after(tool, tool_call, tool_result):
        after_calls.append(tool_result.name)

    model = llm.get_async_model("echo")
    chain = model.chain(
        json.dumps({"tool_calls": [{"name": "needs_input"}, {"name": "sibling"}]}),
        tools=[needs_input, sibling],
        after_call=after,
    )
    with pytest.raises(llm.PauseChain) as exc_info:
        await chain.text()

    pause = exc_info.value
    assert pause.tool_call.name == "needs_input"
    # The concurrent sibling ran to completion - no orphaned tasks
    assert executed == ["sibling"]
    assert after_calls == ["sibling"]
    # Completed sibling results ride on the exception
    assert [r.name for r in pause.tool_results] == ["sibling"]
    assert pause.tool_results[0].output == "done"


def test_pause_chain_sync_model_stops_remaining_calls():
    executed = []

    def pauser() -> str:
        raise llm.PauseChain("wait")

    def later() -> str:
        executed.append("later")
        return "x"

    model = llm.get_model("echo")
    chain = model.chain(
        json.dumps({"tool_calls": [{"name": "pauser"}, {"name": "later"}]}),
        tools=[pauser, later],
    )
    with pytest.raises(llm.PauseChain) as exc_info:
        chain.text()
    # Sequential execution stops at the pause; later call never starts,
    # so it can safely re-execute on resume.
    assert executed == []
    assert exc_info.value.tool_results == []


@pytest.mark.asyncio
async def test_pause_chain_async_first_of_two_pauses_propagates():
    async def pause_a() -> str:
        raise llm.PauseChain("a")

    async def pause_b() -> str:
        raise llm.PauseChain("b")

    model = llm.get_async_model("echo")
    chain = model.chain(
        json.dumps({"tool_calls": [{"name": "pause_a"}, {"name": "pause_b"}]}),
        tools=[pause_a, pause_b],
    )
    with pytest.raises(llm.PauseChain) as exc_info:
        await chain.text()
    assert str(exc_info.value) == "a"
    assert exc_info.value.tool_call.name == "pause_a"


@pytest.mark.asyncio
async def test_async_hook_exception_does_not_orphan_siblings():
    """Defined failure semantics: an exception raised by an after_call
    hook propagates only after all concurrent tool tasks finish."""
    executed = []

    async def boomer() -> str:
        return "boom"

    async def slow() -> str:
        await asyncio.sleep(0.05)
        executed.append("slow")
        return "ok"

    async def after(tool, tool_call, tool_result):
        if tool_result.name == "boomer":
            raise ValueError("hook bug")

    model = llm.get_async_model("echo")
    chain = model.chain(
        json.dumps({"tool_calls": [{"name": "boomer"}, {"name": "slow"}]}),
        tools=[boomer, slow],
        after_call=after,
    )
    with pytest.raises(ValueError, match="hook bug"):
        await chain.text()
    # The slow sibling was not orphaned mid-flight
    assert executed == ["slow"]


@pytest.mark.asyncio
async def test_pause_chain_async_model_sync_tool():
    def pauser() -> str:
        raise llm.PauseChain("wait")

    model = llm.get_async_model("echo")
    chain = model.chain(
        json.dumps({"tool_calls": [{"name": "pauser"}]}),
        tools=[pauser],
    )
    with pytest.raises(llm.PauseChain) as exc_info:
        await chain.text()
    assert exc_info.value.tool_call.name == "pauser"


# ---- chain resume from message history ----


def _pending_history(tool_call_id="tc_resume1"):
    return [
        Message(role="user", parts=[TextPart(text="Convert hello to uppercase")]),
        Message(
            role="assistant",
            parts=[
                ToolCallPart(
                    name="upper",
                    arguments={"text": "hello"},
                    tool_call_id=tool_call_id,
                )
            ],
        ),
    ]


def test_chain_resumes_trailing_pending_tool_calls():
    executed = []
    hook_calls = []

    def upper(text: str) -> str:
        executed.append(text)
        return text.upper()

    def before(tool, tool_call):
        hook_calls.append(("before", tool_call.name, tool_call.tool_call_id))

    def after(tool, tool_call, tool_result):
        hook_calls.append(("after", tool_result.name, tool_result.tool_call_id))

    model = llm.get_model("echo")
    chain = model.chain(
        None,
        messages=_pending_history(),
        tools=[upper],
        before_call=before,
        after_call=after,
    )
    output = chain.text()

    # The pending call executed through the normal hook machinery
    assert executed == ["hello"]
    assert hook_calls == [
        ("before", "upper", "tc_resume1"),
        ("after", "upper", "tc_resume1"),
    ]
    # The model then received the tool result (echo renders
    # prompt.tool_results), correlated by the original id
    data = json.loads(output)
    assert data["tool_results"] == [
        {"name": "upper", "output": "HELLO", "tool_call_id": "tc_resume1"}
    ]
    # Exactly one provider call was made
    assert len(chain._responses) == 1


@pytest.mark.asyncio
async def test_chain_resumes_trailing_pending_tool_calls_async():
    executed = []

    async def upper(text: str) -> str:
        executed.append(text)
        return text.upper()

    model = llm.get_async_model("echo")
    chain = model.chain(None, messages=_pending_history(), tools=[upper])
    output = await chain.text()

    assert executed == ["hello"]
    data = json.loads(output)
    assert data["tool_results"] == [
        {"name": "upper", "output": "HELLO", "tool_call_id": "tc_resume1"}
    ]


def test_resume_skips_calls_that_already_have_results():
    executed = []

    def first() -> str:
        executed.append("first")
        return "one"

    def second() -> str:
        executed.append("second")
        return "two"

    history = [
        Message(role="user", parts=[TextPart(text="go")]),
        Message(
            role="assistant",
            parts=[
                ToolCallPart(name="first", arguments={}, tool_call_id="tc_a"),
                ToolCallPart(name="second", arguments={}, tool_call_id="tc_b"),
            ],
        ),
        Message(
            role="tool",
            parts=[ToolResultPart(name="first", output="one", tool_call_id="tc_a")],
        ),
    ]
    model = llm.get_model("echo")
    chain = model.chain(None, messages=history, tools=[first, second])
    output = chain.text()

    assert executed == ["second"]
    data = json.loads(output)
    assert data["tool_results"] == [
        {"name": "second", "output": "two", "tool_call_id": "tc_b"}
    ]


def test_no_resume_when_conversation_moved_on():
    executed = []

    def upper(text: str) -> str:
        executed.append(text)
        return text.upper()

    history = _pending_history() + [
        Message(role="user", parts=[TextPart(text="never mind")]),
    ]
    model = llm.get_model("echo")
    chain = model.chain(None, messages=history, tools=[upper])
    chain.text()
    assert executed == []


def test_no_resume_without_tools():
    model = llm.get_model("echo")
    chain = model.chain(None, messages=_pending_history())
    # No tools provided: nothing to execute, chain proceeds normally
    output = chain.text()
    assert "tool_results" not in json.loads(output)


def test_resume_matches_idless_calls_by_name():
    # Histories persisted before guaranteed ids may have None ids
    executed = []

    def upper(text: str) -> str:
        executed.append(text)
        return text.upper()

    history = [
        Message(role="user", parts=[TextPart(text="go")]),
        Message(
            role="assistant",
            parts=[
                ToolCallPart(name="upper", arguments={"text": "a"}, tool_call_id=None),
                ToolCallPart(name="upper", arguments={"text": "b"}, tool_call_id=None),
            ],
        ),
        Message(
            role="tool",
            parts=[ToolResultPart(name="upper", output="A", tool_call_id=None)],
        ),
    ]
    model = llm.get_model("echo")
    chain = model.chain(None, messages=history, tools=[upper])
    chain.text()
    # One result already present: only one of the two calls re-executes
    assert executed == ["b"]


def test_resume_ignores_server_executed_calls():
    executed = []

    def upper(text: str) -> str:
        executed.append(text)
        return text.upper()

    history = [
        Message(role="user", parts=[TextPart(text="go")]),
        Message(
            role="assistant",
            parts=[
                ToolCallPart(
                    name="upper",
                    arguments={"text": "x"},
                    tool_call_id="tc_srv",
                    server_executed=True,
                )
            ],
        ),
    ]
    model = llm.get_model("echo")
    chain = model.chain(None, messages=history, tools=[upper])
    chain.text()
    assert executed == []


def test_resumed_tool_can_pause_again():
    def needs_more(text: str) -> str:
        raise llm.PauseChain("second question")

    history = [
        Message(role="user", parts=[TextPart(text="go")]),
        Message(
            role="assistant",
            parts=[
                ToolCallPart(
                    name="needs_more",
                    arguments={"text": "x"},
                    tool_call_id="tc_again",
                )
            ],
        ),
    ]
    model = llm.get_model("echo")
    chain = model.chain(None, messages=history, tools=[needs_more])
    with pytest.raises(llm.PauseChain) as exc_info:
        chain.text()
    assert exc_info.value.tool_call.name == "needs_more"
    assert exc_info.value.tool_call.tool_call_id == "tc_again"
    # No provider call was made: the chain paused before reaching the model
    assert len(chain._responses) == 0
