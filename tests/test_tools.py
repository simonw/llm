import asyncio
from click.testing import CliRunner
from importlib.metadata import version
import json
import llm
from llm import cli, CancelToolCall
from llm.migrations import migrate
from llm.tools import llm_time
import os
import pytest
import sqlite_utils
import time


API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


@pytest.mark.vcr
def test_tool_use_basic(vcr):
    model = llm.get_model("gpt-4o-mini")

    def multiply(a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b

    chain_response = model.chain("What is 1231 * 2331?", tools=[multiply], key=API_KEY)

    output = "".join(chain_response)

    assert output == "The result of \\( 1231 \\times 2331 \\) is \\( 2,869,461 \\)."

    first, second = chain_response._responses

    assert first.prompt.prompt == "What is 1231 * 2331?"
    assert first.prompt.tools[0].name == "multiply"

    assert len(second.prompt.tool_results) == 1
    assert second.prompt.tool_results[0].name == "multiply"
    assert second.prompt.tool_results[0].output == "2869461"

    # Test writing to the database
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    chain_response.log_to_db(db)
    assert set(db.table_names()).issuperset(
        {"tools", "tool_responses", "tool_calls", "tool_results"}
    )

    responses = list(db["responses"].rows)
    assert len(responses) == 2
    first_response, second_response = responses

    tools = list(db["tools"].rows)
    assert len(tools) == 1
    assert tools[0]["name"] == "multiply"
    assert tools[0]["description"] == "Multiply two numbers."
    assert tools[0]["plugin"] is None

    tool_results = list(db["tool_results"].rows)
    tool_calls = list(db["tool_calls"].rows)

    assert len(tool_calls) == 1
    assert tool_calls[0]["response_id"] == first_response["id"]
    assert tool_calls[0]["name"] == "multiply"
    assert tool_calls[0]["arguments"] == '{"a": 1231, "b": 2331}'

    assert len(tool_results) == 1
    assert tool_results[0]["response_id"] == second_response["id"]
    assert tool_results[0]["output"] == "2869461"
    assert tool_results[0]["tool_call_id"] == tool_calls[0]["tool_call_id"]


@pytest.mark.vcr
def test_tool_use_chain_of_two_calls(vcr):
    model = llm.get_model("gpt-4o-mini")

    def lookup_population(country: str) -> int:
        "Returns the current population of the specified fictional country"
        return 123124

    def can_have_dragons(population: int) -> bool:
        "Returns True if the specified population can have dragons, False otherwise"
        return population > 10000

    chain_response = model.chain(
        "Can the country of Crumpet have dragons? Answer with only YES or NO",
        tools=[lookup_population, can_have_dragons],
        stream=False,
        key=API_KEY,
    )

    output = chain_response.text()
    assert output == "YES"
    assert len(chain_response._responses) == 3

    first, second, third = chain_response._responses
    assert first.tool_calls()[0].arguments == {"country": "Crumpet"}
    assert first.prompt.tool_results == []
    assert second.prompt.tool_results[0].output == "123124"
    assert second.tool_calls()[0].arguments == {"population": 123124}
    assert third.prompt.tool_results[0].output == "true"
    assert third.tool_calls() == []


def test_tool_use_async_tool_function():
    async def hello():
        return "world"

    model = llm.get_model("echo")
    chain_response = model.chain(
        json.dumps({"tool_calls": [{"name": "hello"}]}), tools=[hello]
    )
    output = chain_response.text()
    # That's two JSON objects separated by '\n}{\n'
    bits = output.split("\n}{\n")
    assert len(bits) == 2
    objects = [json.loads(bits[0] + "}"), json.loads("{" + bits[1])]
    assert objects == [
        {"prompt": "", "system": "", "attachments": [], "stream": True, "previous": []},
        {
            "prompt": "",
            "system": "",
            "attachments": [],
            "stream": True,
            "previous": [{"prompt": '{"tool_calls": [{"name": "hello"}]}'}],
            "tool_results": [
                {"name": "hello", "output": "world", "tool_call_id": None}
            ],
        },
    ]


@pytest.mark.asyncio
async def test_async_tools_run_tools_in_parallel():
    start_timestamps = []

    start_ns = time.monotonic_ns()

    async def hello():
        start_timestamps.append(("hello", time.monotonic_ns() - start_ns))
        await asyncio.sleep(0.2)
        return "world"

    async def hello2():
        start_timestamps.append(("hello2", time.monotonic_ns() - start_ns))
        await asyncio.sleep(0.2)
        return "world2"

    model = llm.get_async_model("echo")
    chain_response = model.chain(
        json.dumps({"tool_calls": [{"name": "hello"}, {"name": "hello2"}]}),
        tools=[hello, hello2],
    )
    output = await chain_response.text()
    # That's two JSON objects separated by '\n}{\n'
    bits = output.split("\n}{\n")
    assert len(bits) == 2
    objects = [json.loads(bits[0] + "}"), json.loads("{" + bits[1])]
    assert objects == [
        {"prompt": "", "system": "", "attachments": [], "stream": True, "previous": []},
        {
            "prompt": "",
            "system": "",
            "attachments": [],
            "stream": True,
            "previous": [
                {"prompt": '{"tool_calls": [{"name": "hello"}, {"name": "hello2"}]}'}
            ],
            "tool_results": [
                {"name": "hello", "output": "world", "tool_call_id": None},
                {"name": "hello2", "output": "world2", "tool_call_id": None},
            ],
        },
    ]
    delta_ns = start_timestamps[1][1] - start_timestamps[0][1]
    # They should have run in parallel so it should be less than 0.02s difference
    assert delta_ns < (100_000_000 * 0.2)


@pytest.mark.asyncio
async def test_async_toolbox():
    class Tools(llm.Toolbox):
        async def go(self):
            return "This was async"

    model = llm.get_async_model("echo")
    chain_response = model.chain(
        json.dumps({"tool_calls": [{"name": "Tools_go"}]}),
        tools=[Tools()],
    )
    output = await chain_response.text()
    assert '"output": "This was async"' in output


@pytest.mark.vcr
def test_conversation_with_tools(vcr):
    import llm

    def add(a: int, b: int) -> int:
        return a + b

    def multiply(a: int, b: int) -> int:
        return a * b

    model = llm.get_model("echo")
    conversation = model.conversation(tools=[add, multiply])

    output1 = conversation.chain(
        json.dumps(
            {"tool_calls": [{"name": "multiply", "arguments": {"a": 5324, "b": 23233}}]}
        )
    ).text()
    assert "123692492" in output1
    output2 = conversation.chain(
        json.dumps(
            {
                "tool_calls": [
                    {"name": "add", "arguments": {"a": 841758375, "b": 123123}}
                ]
            }
        )
    ).text()
    assert "841881498" in output2


def test_default_tool_llm_version():
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "-m",
            "echo",
            "-T",
            "llm_version",
            json.dumps({"tool_calls": [{"name": "llm_version"}]}),
        ],
    )
    assert result.exit_code == 0
    assert '"output": "{}"'.format(version("llm")) in result.output


def test_functions_tool_locals():
    # https://github.com/simonw/llm/issues/1107
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "-m",
            "echo",
            "--functions",
            "my_locals = locals",
            "-T",
            "llm_version",
            json.dumps({"tool_calls": [{"name": "locals"}]}),
        ],
    )
    assert result.exit_code == 0


def test_default_tool_llm_time():
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "-m",
            "echo",
            "-T",
            "llm_time",
            json.dumps({"tool_calls": [{"name": "llm_time"}]}),
        ],
    )
    assert result.exit_code == 0
    assert "timezone_offset" in result.output

    # Test it by calling it directly
    info = llm_time()
    assert set(info.keys()) == {
        "timezone_offset",
        "utc_time_iso",
        "local_time",
        "local_timezone",
        "utc_time",
        "is_dst",
    }


def test_incorrect_tool_usage():
    model = llm.get_model("echo")

    def simple(name: str):
        return name

    chain_response = model.chain(
        json.dumps({"tool_calls": [{"name": "bad_tool"}]}),
        tools=[simple],
    )
    output = chain_response.text()
    assert 'Error: tool \\"bad_tool\\" does not exist' in output


def test_tool_returning_attachment():
    model = llm.get_model("echo")

    def return_attachment() -> llm.Attachment:
        return llm.ToolOutput(
            "Output",
            attachments=[
                llm.Attachment(
                    content=b"This is a test attachment",
                    type="image/png",
                )
            ],
        )

    chain_response = model.chain(
        json.dumps({"tool_calls": [{"name": "return_attachment"}]}),
        tools=[return_attachment],
    )
    output = chain_response.text()
    assert '"type": "image/png"' in output
    assert '"output": "Output"' in output


@pytest.mark.asyncio
async def test_async_tool_returning_attachment():
    model = llm.get_async_model("echo")

    async def return_attachment() -> llm.Attachment:
        return llm.ToolOutput(
            "Output",
            attachments=[
                llm.Attachment(
                    content=b"This is a test attachment",
                    type="image/png",
                )
            ],
        )

    chain_response = model.chain(
        json.dumps({"tool_calls": [{"name": "return_attachment"}]}),
        tools=[return_attachment],
    )
    output = await chain_response.text()
    assert '"type": "image/png"' in output
    assert '"output": "Output"' in output


def test_tool_conversation_settings():
    model = llm.get_model("echo")
    before_collected = []
    after_collected = []

    def before(*args):
        before_collected.append(args)

    def after(*args):
        after_collected.append(args)

    conversation = model.conversation(
        tools=[llm_time], before_call=before, after_call=after
    )
    # Run two things
    conversation.chain(json.dumps({"tool_calls": [{"name": "llm_time"}]})).text()
    conversation.chain(json.dumps({"tool_calls": [{"name": "llm_time"}]})).text()
    assert len(before_collected) == 2
    assert len(after_collected) == 2


@pytest.mark.asyncio
async def test_tool_conversation_settings_async():
    model = llm.get_async_model("echo")
    before_collected = []
    after_collected = []

    async def before(*args):
        before_collected.append(args)

    async def after(*args):
        after_collected.append(args)

    conversation = model.conversation(
        tools=[llm_time], before_call=before, after_call=after
    )
    await conversation.chain(json.dumps({"tool_calls": [{"name": "llm_time"}]})).text()
    await conversation.chain(json.dumps({"tool_calls": [{"name": "llm_time"}]})).text()
    assert len(before_collected) == 2
    assert len(after_collected) == 2


ERROR_FUNCTION = """
def trigger_error(msg: str):
    raise Exception(msg)
"""


@pytest.mark.parametrize("async_", (False, True))
def test_tool_errors(async_):
    # https://github.com/simonw/llm/issues/1107
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        (
            [
                "-m",
                "echo",
                "--functions",
                ERROR_FUNCTION,
                json.dumps(
                    {
                        "tool_calls": [
                            {"name": "trigger_error", "arguments": {"msg": "Error!"}}
                        ]
                    }
                ),
            ]
            + (["--async"] if async_ else [])
        ),
    )
    assert result.exit_code == 0
    assert '"output": "Error: Error!"' in result.output
    # llm logs --json output
    log_json_result = runner.invoke(cli.cli, ["logs", "--json", "-c"])
    assert log_json_result.exit_code == 0
    log_data = json.loads(log_json_result.output)
    assert len(log_data) == 2
    assert log_data[1]["tool_results"][0]["exception"] == "Exception: Error!"
    # llm logs -c output
    log_text_result = runner.invoke(cli.cli, ["logs", "-c"])
    assert log_text_result.exit_code == 0
    assert (
        "- **trigger_error**: `None`<br>\n"
        "    Error: Error!<br>\n"
        "    **Error**: Exception: Error!\n"
    ) in log_text_result.output


def test_chain_sync_cancel_only_first_of_two():
    model = llm.get_model("echo")

    def t1() -> str:
        return "ran1"

    def t2() -> str:
        return "ran2"

    def before(tool, tool_call):
        if tool.name == "t1":
            raise CancelToolCall("skip1")
        # allow t2
        return None

    calls = [
        {"name": "t1"},
        {"name": "t2"},
    ]
    payload = json.dumps({"tool_calls": calls})
    chain = model.chain(payload, tools=[t1, t2], before_call=before)
    _ = chain.text()

    # second response has two results
    second = chain._responses[1]
    results = second.prompt.tool_results
    assert len(results) == 2

    # first cancelled, second executed
    assert results[0].name == "t1"
    assert results[0].output == "Cancelled: skip1"
    assert isinstance(results[0].exception, CancelToolCall)

    assert results[1].name == "t2"
    assert results[1].output == "ran2"
    assert results[1].exception is None


# 2c async equivalent
@pytest.mark.asyncio
async def test_chain_async_cancel_only_first_of_two():
    async_model = llm.get_async_model("echo")

    def t1() -> str:
        return "ran1"

    async def t2() -> str:
        return "ran2"

    async def before(tool, tool_call):
        if tool.name == "t1":
            raise CancelToolCall("skip1")
        return None

    calls = [
        {"name": "t1"},
        {"name": "t2"},
    ]
    payload = json.dumps({"tool_calls": calls})
    chain = async_model.chain(payload, tools=[t1, t2], before_call=before)
    _ = await chain.text()

    second = chain._responses[1]
    results = second.prompt.tool_results
    assert len(results) == 2

    assert results[0].name == "t1"
    assert results[0].output == "Cancelled: skip1"
    assert isinstance(results[0].exception, CancelToolCall)

    assert results[1].name == "t2"
    assert results[1].output == "ran2"
    assert results[1].exception is None
