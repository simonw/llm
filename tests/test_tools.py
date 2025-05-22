import asyncio
import json
import llm
from llm.migrations import migrate
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
