import llm
from llm.migrations import migrate
import os
import pytest
import sqlite_utils


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
