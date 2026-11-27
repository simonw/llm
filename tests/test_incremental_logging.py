import json

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.logs import LogStore, log_row_extras, merged_log_rows
from llm.plugins import pm


@pytest.fixture
def incremental_model(monkeypatch, mock_model, async_mock_model, db_factory, user_path):
    """A tool chain that observes committed logs from a separate connection."""
    state = {"tool_snapshots": [], "model_snapshots": [], "calls": 0}

    def read_rows():
        db = db_factory(str(user_path / "logs.db"))
        store = LogStore(db)
        return [
            {**row, **log_row_extras(store, row)}
            for row in reversed(merged_log_rows(store))
        ]

    def snapshot():
        return [row["response"] for row in read_rows()]

    def checkpoint():
        state["tool_snapshots"].append(snapshot())
        if state["outcome"] == "tool-interrupt":
            raise KeyboardInterrupt()
        return "tool result"

    class Plugin:
        @llm.hookimpl
        def register_tools(self, register):
            register(checkpoint)

    plugin = Plugin()
    pm.register(plugin, name="incremental-logging-test")

    def configure(async_=False, outcome="success"):
        state["outcome"] = outcome

        def execute(prompt, stream, response, conversation):
            state["calls"] += 1
            if state["calls"] > 1:
                state["model_snapshots"].append(snapshot())
                if outcome in ("model-error", "interrupt"):
                    yield "Unfinished response"
                    if outcome == "interrupt":
                        raise KeyboardInterrupt()
                    raise RuntimeError("Model failed during the next round")
            if state["calls"] == 1 or outcome == "limit":
                response.add_tool_call(
                    llm.ToolCall(
                        name="checkpoint",
                        arguments={},
                        tool_call_id="call-{}".format(state["calls"]),
                    )
                )
            yield "Round {}".format(state["calls"])
            response.set_usage(input=3, output=2)

        async def async_execute(prompt, stream, response, conversation):
            for chunk in execute(prompt, stream, response, conversation):
                yield chunk

        model = async_mock_model if async_ else mock_model
        monkeypatch.setattr(model, "supports_tools", True)
        monkeypatch.setattr(model, "execute", async_execute if async_ else execute)
        return state, read_rows

    try:
        yield configure
    finally:
        pm.unregister(plugin)


@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize(
    "outcome", ("limit", "model-error", "interrupt", "tool-interrupt")
)
def test_prompt_keeps_completed_rounds(incremental_model, async_, stream, outcome):
    state, read_rows = incremental_model(async_=async_, outcome=outcome)
    args = ["-m", "mock", "-T", "checkpoint", "Start", "--cl", "2"]
    if async_:
        args.append("--async")
    if not stream:
        args.append("--no-stream")
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    if outcome == "limit":
        assert "Chain limit of 2 exceeded" in result.output
    elif outcome == "model-error":
        assert isinstance(result.exception, RuntimeError)
    else:
        assert "Aborted!" in result.output
    expected = ["Round 1", "Round 2"] if outcome == "limit" else ["Round 1"]
    rows = read_rows()
    assert [row["response"] for row in rows] == expected
    assert rows[0]["prompt"] == "Start"
    assert rows[0]["input_tokens"] == 3
    assert rows[0]["output_tokens"] == 2
    assert rows[0]["tool_calls"][0]["tool_call_id"] == "call-1"
    # Commit before executing tools, not just in a finally block after failure.
    assert state["tool_snapshots"] == [["Round 1"]]
    if outcome != "tool-interrupt":
        assert state["model_snapshots"] == [["Round 1"]]


@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize(
    "outcome", ("limit", "model-error", "interrupt", "tool-interrupt")
)
def test_chat_keeps_completed_rounds(incremental_model, stream, outcome):
    state, read_rows = incremental_model(outcome=outcome)
    args = ["chat", "-m", "mock", "-T", "checkpoint", "--cl", "2"]
    if not stream:
        args.append("--no-stream")
    result = CliRunner().invoke(cli, args, input="Start\nquit\n")
    assert result.exit_code != 0
    expected = ["Round 1", "Round 2"] if outcome == "limit" else ["Round 1"]
    assert [row["response"] for row in read_rows()] == expected
    assert state["tool_snapshots"] == [["Round 1"]]


@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize("stream", (False, True))
def test_completed_chain_logs_each_round_once(
    incremental_model, monkeypatch, async_, stream
):
    state, read_rows = incremental_model(async_=async_)
    logged_ids = []
    original_log = LogStore.log

    def log(store, response, thread_id=None):
        logged_ids.append(response.id)
        return original_log(store, response, thread_id=thread_id)

    monkeypatch.setattr(LogStore, "log", log)
    args = ["-m", "mock", "-T", "checkpoint", "Start"]
    if async_:
        args.append("--async")
    if not stream:
        args.append("--no-stream")
    result = CliRunner().invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    rows = read_rows()
    assert [row["response"] for row in rows] == ["Round 1", "Round 2"]
    assert len({row["id"] for row in rows}) == 2
    assert logged_ids == [row["id"] for row in rows]
    assert len({row["conversation_id"] for row in rows}) == 1
    assert rows[1]["tool_results"][0]["output"] == "tool result"
    assert state["tool_snapshots"] == [["Round 1"]]
    assert state["model_snapshots"] == [["Round 1"]]


@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize(
    "logs_off,flags,expected_logging",
    (
        (False, ["--no-log"], False),
        (True, [], False),
        (True, ["--log"], True),
        (False, ["--json"], True),
        (False, ["--json", "--no-log"], False),
        (True, ["--json"], False),
    ),
)
def test_incremental_logging_options(
    incremental_model, async_, logs_off, flags, expected_logging
):
    state, read_rows = incremental_model(async_=async_)
    runner = CliRunner()
    if logs_off:
        result = runner.invoke(cli, ["logs", "off"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
    args = ["-m", "mock", "-T", "checkpoint", "Start", *flags]
    if async_:
        args.append("--async")
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    rows = read_rows()
    assert [row["response"] for row in rows] == (
        ["Round 1", "Round 2"] if expected_logging else []
    )
    assert state["tool_snapshots"] == [["Round 1"] if expected_logging else []]
    assert state["model_snapshots"] == [["Round 1"] if expected_logging else []]
    if "--json" in flags:
        output = json.loads(result.output)
        assert [row["response"] for row in output] == ["Round 1", "Round 2"]
        assert output[1]["tool_results"][0]["output"] == "tool result"
