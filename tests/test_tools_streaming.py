import os

import pytest

import llm
from llm.tools import llm_version

API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


# This response contains streaming variant "a" where arguments="" is followed by arguments="{}"
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_a():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert "".join(chain) == "The current version of *llm* is **0.fixed-version**."


# This response contains streaming variant "b" where arguments="{}" is the first partial stream received.
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_b():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert "".join(chain) == "The current version of *llm* is **0.fixed-version**."


# This response contains streaming variant "c".
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_c():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert (
        "".join(chain)
        == "The installed version of LLM on this system is 0.fixed-version."
    )


# This response contains streaming variant "d" where a no-argument tool call
# streams arguments=null and never sends a "{}" chunk, so the accumulated
# arguments string stays empty - json.loads("") used to raise here.
@pytest.mark.vcr(record_mode="none")
def test_tools_streaming_variant_d():
    model = llm.get_model("gpt-4.1-mini")
    chain = model.chain(
        "What is the current llm version?", tools=[llm_version], key=API_KEY
    )
    assert "".join(chain) == "The current version of *llm* is **0.fixed-version**."


@pytest.mark.asyncio
@pytest.mark.parametrize("async_", [False, True])
async def test_streaming_tool_calls_without_index(httpx2_mock, async_):
    # Some OpenAI-compatible endpoints omit "index" on streamed tool calls
    import json

    from pytest_httpx2 import IteratorStream

    fragments = [
        ("call_first", "first", '{"value":'),
        (None, None, "1}"),
        ("call_second", "second", '{"value":'),
        (None, None, "2}"),
    ]
    chunks = []
    for call_id, name, arguments in fragments:
        tool_call = {
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }
        if call_id:
            tool_call["id"] = call_id
        chunk = {
            "id": "chat_test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gpt-4.1-mini",
            "choices": [{"index": 0, "delta": {"tool_calls": [tool_call]}}],
        }
        chunks.append(("data: " + json.dumps(chunk) + "\n\n").encode())
    chunks.append(b"data: [DONE]\n\n")
    httpx2_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        stream=IteratorStream(chunks),
        headers={"Content-Type": "text/event-stream"},
    )
    model = (llm.get_async_model if async_ else llm.get_model)("gpt-4.1-mini")
    response = model.prompt("Call both tools", key=API_KEY, stream=True)
    if async_:
        [event async for event in response.astream_events()]
        calls = await response.tool_calls()
    else:
        list(response.stream_events())
        calls = response.tool_calls()
    assert [(call.tool_call_id, call.name, call.arguments) for call in calls] == [
        ("call_first", "first", {"value": 1}),
        ("call_second", "second", {"value": 2}),
    ]
