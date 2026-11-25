import json

import pytest

import llm


class Lookup:
    def __init__(self):
        self.calls = []

    def __call__(self, number: int) -> str:
        """Look up a numbered record."""
        self.calls.append(number)
        return f"record:{number}"


@pytest.mark.parametrize("name", [None, "lookup_record"])
def test_callable_instance_tool(name):
    lookup = Lookup()
    tool = llm.Tool.function(lookup, name=name)
    assert tool.name == (name or "Lookup")
    assert tool.description == "Look up a numbered record."
    assert tool.input_schema["properties"] == {"number": {"type": "integer"}}
    assert tool.input_schema["required"] == ["number"]

    chain = llm.get_model("echo").chain(
        json.dumps({"tool_calls": [{"name": tool.name, "arguments": {"number": 7}}]}),
        tools=[tool],
    )
    chain.text()
    result = chain._responses[1].prompt.tool_results[0]
    assert result.output == "record:7"
    assert result.exception is None
    assert lookup.calls == [7]


def test_callable_instance_in_tools_list():
    lookup = Lookup()
    chain = llm.get_model("echo").chain(
        json.dumps({"tool_calls": [{"name": "Lookup", "arguments": {"number": 4}}]}),
        tools=[lookup],
    )
    chain.text()
    assert lookup.calls == [4]
    assert chain._responses[1].prompt.tool_results[0].output == "record:4"


@pytest.mark.asyncio
async def test_callable_instance_in_async_tools_list():
    lookup = Lookup()
    chain = llm.get_async_model("echo").chain(
        json.dumps({"tool_calls": [{"name": "Lookup", "arguments": {"number": 5}}]}),
        tools=[lookup],
    )
    await chain.text()
    assert lookup.calls == [5]
    assert chain._responses[1].prompt.tool_results[0].output == "record:5"
