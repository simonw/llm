"""Cancellation and ordinary failure ownership for asynchronous tool calls."""

import asyncio

import pytest

import llm


class OfflineModel(llm.AsyncModel):
    model_id = "offline-cancellation-probe"
    supports_tools = True

    async def execute(self, prompt, stream, response, conversation):
        raise AssertionError("The probe must not invoke a model")
        yield ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "branch", ["sync_hook", "missing_hook", "awaitable", "after_hook", "all_async"]
)
async def test_cancel_does_not_leave_tool_side_effects_running(branch):
    started = asyncio.Event()
    blocked = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    side_effects = []
    tasks = []

    async def sibling():
        tasks.append(asyncio.current_task())
        started.set()
        try:
            await release.wait()
            side_effects.append("ran after the enclosing call was canceled")
            return "done"
        finally:
            await asyncio.sleep(0)
            closed.set()

    async def block():
        await started.wait()
        blocked.set()
        await asyncio.Event().wait()

    def inline():
        if branch == "awaitable":
            return block()
        if branch == "after_hook":
            return "inline completed"
        raise AssertionError("Hook should be canceled before implementation")

    async def before_call(tool, call):
        if call.name == "second" and branch in {"sync_hook", "missing_hook"}:
            await block()

    async def after_call(tool, call, result):
        if call.name == "second" and branch == "after_hook":
            await block()

    tools = [llm.Tool(name="sibling", implementation=sibling)]
    if branch != "missing_hook":
        tools.append(
            llm.Tool(
                name="second", implementation=block if branch == "all_async" else inline
            )
        )
    response = OfflineModel().prompt("offline", tools=tools)
    execution = asyncio.create_task(
        response.execute_tool_calls(
            tool_calls_list=[
                llm.ToolCall(name="sibling", arguments={}),
                llm.ToolCall(name="second", arguments={}),
            ],
            before_call=before_call,
            after_call=after_call,
        )
    )
    try:
        await asyncio.wait_for(blocked.wait(), 5)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
        owned_children_done_on_return = all(task.done() for task in tasks)
        # Let any orphan finish in a controlled way; all_async is a passing
        # control because cancellation already reached the asyncio.gather.
        release.set()
        await asyncio.wait_for(closed.wait(), 5)
        assert (
            owned_children_done_on_return
        ), f"branch={branch}; child_done_on_parent_return={owned_children_done_on_return}; late_side_effects={side_effects!r}"
        assert not side_effects
    finally:
        execution.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(execution, *tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["hook_error", "pause"])
async def test_ordinary_failure_waits_for_started_siblings(failure):
    completed = []
    second_completed = asyncio.Event()

    async def first():
        await second_completed.wait()
        completed.append("first")
        return "first result"

    async def second():
        completed.append("second")
        second_completed.set()
        return "second result"

    def third():
        raise llm.PauseChain("approval needed")

    def before_call(tool, call):
        if call.name == "third" and failure == "hook_error":
            raise ValueError("hook failed")

    response = OfflineModel().prompt(
        "offline",
        tools=[
            llm.Tool(name="first", implementation=first),
            llm.Tool(name="second", implementation=second),
            llm.Tool(name="third", implementation=third),
        ],
    )
    expected = ValueError if failure == "hook_error" else llm.PauseChain
    with pytest.raises(expected) as raised:
        await response.execute_tool_calls(
            tool_calls_list=[
                llm.ToolCall(name="first", arguments={}, tool_call_id="first-id"),
                llm.ToolCall(name="second", arguments={}, tool_call_id="second-id"),
                llm.ToolCall(name="third", arguments={}, tool_call_id="third-id"),
            ],
            before_call=before_call,
        )
    assert completed == ["second", "first"]
    if failure == "pause":
        assert raised.value.tool_call.name == "third"
        assert [
            (r.name, r.output, r.tool_call_id) for r in raised.value.tool_results
        ] == [
            ("first", "first result", "first-id"),
            ("second", "second result", "second-id"),
        ]
