import json

import pytest

import llm


def lookup(query: str, *extra: str, limit: int = 3) -> str:
    return f"{query}:{limit}:{len(extra)}"


def lookup_with_options(query: str, **options: str) -> str:
    return f"{query}:{options}"


@pytest.mark.parametrize("function", [lookup, lookup_with_options])
def test_variadic_parameters_are_not_required_fields(function):
    schema = llm.Tool.function(function).input_schema
    assert schema["required"] == ["query"]
    assert "extra" not in schema["properties"]
    assert "options" not in schema["properties"]
    if function is lookup:
        assert schema["properties"]["limit"] == {"type": "integer", "default": 3}


def test_declared_required_arguments_can_be_called():
    tool = llm.Tool.function(lookup)
    # Supply every required field, as a model following the declaration would.
    arguments = {key: "example" for key in tool.input_schema["required"]}
    response = llm.get_model("echo").prompt("", tools=[tool])
    results = response.execute_tool_calls(
        tool_calls_list=[llm.ToolCall(name="lookup", arguments=arguments)]
    )
    assert results[0].exception is None
    assert results[0].output == "example:3:0"


@pytest.mark.asyncio
async def test_async_tool_keeps_named_arguments_and_defaults():
    async def fetch(query: str, *extra: str, limit: int = 3, **options: str) -> str:
        return json.dumps([query, extra, limit, options])

    tool = llm.Tool.function(fetch)
    assert tool.input_schema["required"] == ["query"]
    response = llm.get_async_model("echo").prompt("", tools=[tool])
    results = await response.execute_tool_calls(
        tool_calls_list=[
            llm.ToolCall(name="fetch", arguments={"query": "hi", "limit": 2})
        ]
    )
    assert results[0].exception is None
    assert json.loads(results[0].output) == ["hi", [], 2, {}]
