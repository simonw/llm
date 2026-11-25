import json

import pytest

import llm
from llm.parts import ToolCallPart


class DynamicTools(llm.Toolbox):
    def __init__(self):
        self.preparations = 0
        self.calls = []

    def prepare(self):
        self.preparations += 1

        def lookup(number: int) -> str:
            self.calls.append(number)
            return f"record:{number}"

        self.add_tool(lookup)


@pytest.mark.parametrize("conversation", [False, True])
def test_dynamic_tools_are_in_first_sync_prompt(conversation):
    toolbox = DynamicTools()
    model = llm.get_model("echo")
    target = model.conversation(tools=[toolbox]) if conversation else model
    kwargs = {} if conversation else {"tools": [toolbox]}
    response = target.prompt("hello", **kwargs)
    assert toolbox.preparations == 0
    response.text()
    assert [tool.name for tool in response.prompt.tools] == ["lookup"]
    assert toolbox.preparations == 1


def test_dynamic_sync_toolbox_discovers_and_executes_once():
    toolbox = DynamicTools()
    conversation = llm.get_model("echo").conversation(tools=[toolbox])
    for number in [4, 5]:
        chain = conversation.chain(
            json.dumps(
                {"tool_calls": [{"name": "lookup", "arguments": {"number": number}}]}
            )
        )
        chain.text()
        assert chain._responses[-1].prompt.tool_results[0].output == f"record:{number}"
    assert toolbox.preparations == 1
    assert toolbox.calls == [4, 5]


def test_dynamic_sync_toolbox_can_retry_preparation():
    class RetryTools(DynamicTools):
        def prepare(self):
            if self.preparations == 0:
                self.preparations += 1
                raise RuntimeError("discovery failed")
            super().prepare()

    toolbox = RetryTools()
    model = llm.get_model("echo")
    response = model.prompt("hello", tools=[toolbox])
    with pytest.raises(RuntimeError, match="discovery failed"):
        response.text()
    response.text()
    assert [tool.name for tool in response.prompt.tools] == ["lookup"]
    assert toolbox.preparations == 2


def test_dynamic_sync_toolbox_resumes_a_pending_call():
    toolbox = DynamicTools()
    message = llm.Message(
        role="assistant",
        parts=[
            ToolCallPart(name="lookup", arguments={"number": 9}, tool_call_id="call-9")
        ],
    )
    chain = llm.get_model("echo").chain(messages=[message], tools=[toolbox])
    chain.text()
    assert toolbox.calls == [9]
    assert len(chain._responses) == 1
    assert chain._responses[0].prompt.tool_results[0].output == "record:9"


def test_dynamic_sync_toolbox_checks_model_capabilities(mock_model):
    toolbox = DynamicTools()
    mock_model.supports_tools = False
    response = mock_model.prompt("hello", tools=[toolbox])
    with pytest.raises(ValueError, match="does not support tools"):
        response.text()
    assert mock_model.history == []


def test_dynamic_tools_are_refreshed_after_another_response_prepares_them():
    toolbox = DynamicTools()
    model = llm.get_model("echo")
    first = model.prompt("hello", tools=[toolbox])
    second = model.prompt("hello", tools=[toolbox])
    first.text()
    second.text()
    assert [tool.name for tool in second.prompt.tools] == ["lookup"]
    assert toolbox.preparations == 1
