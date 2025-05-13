import llm
import os
import pytest


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
