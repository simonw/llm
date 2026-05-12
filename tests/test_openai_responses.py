"""Tests for the /v1/responses code path in the default OpenAI plugin."""

import json
import os

import llm
import pytest
from pytest_httpx import IteratorStream

API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


def _responses_sse(event_type, data):
    data = {"type": event_type, **data}
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def _responses_reasoning_summary_stream():
    yield _responses_sse(
        "response.reasoning_summary_text.delta",
        {
            "item_id": "rs_1",
            "output_index": 0,
            "summary_index": 0,
            "delta": "Thinking",
            "sequence_number": 1,
        },
    )
    yield _responses_sse(
        "response.reasoning_summary_text.delta",
        {
            "item_id": "rs_1",
            "output_index": 0,
            "summary_index": 0,
            "delta": " aloud",
            "sequence_number": 2,
        },
    )
    yield _responses_sse(
        "response.output_item.done",
        {
            "item": {
                "id": "rs_1",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Thinking aloud"}],
                "encrypted_content": "encrypted",
                "status": "completed",
            },
            "output_index": 0,
            "sequence_number": 3,
        },
    )
    yield _responses_sse(
        "response.output_text.delta",
        {
            "item_id": "msg_1",
            "output_index": 1,
            "content_index": 0,
            "delta": "done",
            "logprobs": [],
            "sequence_number": 4,
        },
    )


def test_responses_model_is_registered():
    model = llm.get_model("gpt-5.5")
    assert "Responses" in type(model).__name__
    # The chat_completions opt-out option must be exposed.
    assert "chat_completions" in model.Options.model_fields


def test_chat_completions_opt_out_dispatches_to_chat(httpx_mock):
    """When chat_completions=1 is passed, the request must hit
    /v1/chat/completions, not /v1/responses."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "model": "gpt-5.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi from chat"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_model("gpt-5.5")
    response = model.prompt("hello", stream=False, chat_completions=True, key="test")
    assert response.text() == "hi from chat"


def test_default_routes_to_responses_endpoint(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_test_1",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.5",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "hi from responses",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
            },
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_model("gpt-5.5")
    response = model.prompt("hello", stream=False, key="test")
    assert response.text() == "hi from responses"
    # Ensure we sent to the right endpoint
    requests = [r for r in httpx_mock.get_requests()]
    assert any("/v1/responses" in str(r.url) for r in requests)
    request_body = json.loads(requests[-1].content)
    assert request_body["include"] == ["reasoning.encrypted_content"]
    assert request_body["reasoning"] == {"summary": "auto"}


def test_hide_reasoning_omits_reasoning_summary_from_responses_request(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_test_1",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.5",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "hidden",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
            },
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_model("gpt-5.5")
    response = model.prompt("hello", stream=False, key="test", hide_reasoning=True)
    assert response.text() == "hidden"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["include"] == ["reasoning.encrypted_content"]
    assert "reasoning" not in request_body


def test_non_reasoning_responses_model_omits_encrypted_reasoning_include(httpx_mock):
    from llm.default_plugins.openai_models import Responses

    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_test_1",
            "object": "response",
            "created_at": 1,
            "model": "gpt-4.1",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "hi from gpt-4.1",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
            },
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )

    model = Responses("gpt-4.1", vision=True, supports_schema=True, supports_tools=True)
    response = model.prompt("hello", stream=False, key="test")

    assert response.text() == "hi from gpt-4.1"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["model"] == "gpt-4.1"
    assert "include" not in request_body
    assert "reasoning" not in request_body


def test_responses_input_translation():
    """Unit-test the message-to-input translator without hitting the API."""
    from llm.parts import (
        Message,
        TextPart,
        ToolCallPart,
        ToolResultPart,
    )

    model = llm.get_model("gpt-5.5")

    class FakePrompt:
        messages = [
            Message(role="system", parts=[TextPart(text="be brief")]),
            Message(role="user", parts=[TextPart(text="2 + 2?")]),
            Message(
                role="assistant",
                parts=[
                    ToolCallPart(
                        name="add",
                        arguments={"a": 2, "b": 2},
                        tool_call_id="call_abc",
                    )
                ],
            ),
            Message(
                role="tool",
                parts=[ToolResultPart(name="add", output="4", tool_call_id="call_abc")],
            ),
        ]

    items, instructions = model._build_responses_input(FakePrompt())
    assert instructions == "be brief"
    # First user message is a plain string content
    assert items[0] == {"role": "user", "content": "2 + 2?"}
    # function_call from assistant
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_abc"
    assert items[1]["name"] == "add"
    assert json.loads(items[1]["arguments"]) == {"a": 2, "b": 2}
    # tool result
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_abc",
        "output": "4",
    }


def test_responses_input_translation_assistant_text_uses_easy_input_message():
    """Plain prior assistant text should match OpenAI's EasyInputMessage shape."""
    from llm.parts import Message, TextPart

    model = llm.get_model("gpt-5.5")

    class FakePrompt:
        messages = [
            Message(role="user", parts=[TextPart(text="hello")]),
            Message(role="assistant", parts=[TextPart(text="first-ok")]),
            Message(role="user", parts=[TextPart(text="what next?")]),
        ]

    items, instructions = model._build_responses_input(FakePrompt())

    assert instructions is None
    assert items == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "first-ok"},
        {"role": "user", "content": "what next?"},
    ]


def test_responses_reply_sends_prior_assistant_text_as_string(httpx_mock):
    """response.reply() should send the same simple history shape a direct
    openai-python Responses call would use for a text-only assistant turn."""

    def response_json(response_id, message_id, text):
        return {
            "id": response_id,
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.5",
            "output": [
                {
                    "type": "message",
                    "id": message_id,
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 3,
                "total_tokens": 8,
            },
            "status": "completed",
        }

    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json=response_json("resp_1", "msg_1", "first-ok"),
        headers={"Content-Type": "application/json"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json=response_json("resp_2", "msg_2", "followup-ok"),
        headers={"Content-Type": "application/json"},
    )

    model = llm.get_model("gpt-5.5")
    first = model.prompt("Say exactly: first-ok", stream=False, key="test")
    second = first.reply("Say exactly: followup-ok", stream=False, key="test")

    assert first.text() == "first-ok"
    assert second.text() == "followup-ok"
    requests = httpx_mock.get_requests()
    second_body = json.loads(requests[-1].content)
    assert second_body["input"] == [
        {"role": "user", "content": "Say exactly: first-ok"},
        {"role": "assistant", "content": "first-ok"},
        {"role": "user", "content": "Say exactly: followup-ok"},
    ]


def test_responses_kwargs_packs_reasoning_and_verbosity():
    model = llm.get_model("gpt-5.5")
    options = model.Options(reasoning_effort="low", verbosity="low")

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert kwargs["reasoning"] == {"summary": "auto", "effort": "low"}
    assert kwargs["text"]["verbosity"] == "low"


def test_responses_kwargs_sets_reasoning_summary_without_effort():
    model = llm.get_model("gpt-5.5")
    options = model.Options()

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert kwargs["reasoning"] == {"summary": "auto"}


def test_responses_kwargs_omits_reasoning_summary_when_hide_reasoning():
    model = llm.get_model("gpt-5.5")
    options = model.Options(reasoning_effort="low")

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    p.hide_reasoning = True
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert kwargs["reasoning"] == {"effort": "low"}


def test_responses_kwargs_omits_empty_reasoning_when_hide_reasoning():
    model = llm.get_model("gpt-5.5")
    options = model.Options()

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    p.hide_reasoning = True
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert "reasoning" not in kwargs


def test_responses_streams_reasoning_summary_text(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        stream=IteratorStream(_responses_reasoning_summary_stream()),
        headers={"Content-Type": "text/event-stream"},
    )

    model = llm.get_model("gpt-5.5")
    response = model.prompt("hello", key="test")
    events = list(response.stream_events())

    assert [(e.type, e.chunk) for e in events] == [
        ("reasoning", "Thinking"),
        ("reasoning", " aloud"),
        ("reasoning", ""),
        ("text", "done"),
    ]
    messages = response.messages()
    reasoning_parts = [
        p for m in messages for p in m.parts if isinstance(p, llm.parts.ReasoningPart)
    ]
    assert reasoning_parts == [
        llm.parts.ReasoningPart(
            text="Thinking aloud",
            provider_metadata={
                "openai": {
                    "id": "rs_1",
                    "encrypted_content": "encrypted",
                    "summary": [{"type": "summary_text", "text": "Thinking aloud"}],
                }
            },
        )
    ]
    assert response.text() == "done"


@pytest.mark.vcr
def test_responses_basic_non_streaming(vcr):
    model = llm.get_model("gpt-5.5")
    response = model.prompt(
        "Reply with exactly: pong",
        stream=False,
        reasoning_effort="low",
        key=API_KEY,
    )
    text = response.text()
    assert "pong" in text.lower()
    # response_json should reflect the Responses API shape
    assert response.response_json["object"] == "response"


@pytest.mark.vcr
def test_responses_basic_streaming(vcr):
    model = llm.get_model("gpt-5.5")
    response = model.prompt(
        "Reply with exactly: pong",
        reasoning_effort="low",
        key=API_KEY,
    )
    chunks = list(response)
    text = "".join(chunks)
    assert "pong" in text.lower()


@pytest.mark.vcr
def test_responses_tool_use(vcr):
    model = llm.get_model("gpt-5.5")

    def multiply(a: int, b: int) -> int:
        "Multiply two numbers."
        return a * b

    chain = model.chain(
        "What is 1231 * 2331? Use the multiply tool.",
        tools=[multiply],
        stream=False,
        options={"reasoning_effort": "low"},
        key=API_KEY,
    )
    output = chain.text()
    assert "2869461" in output.replace(",", "")
    first, second = chain._responses
    assert first.tool_calls()[0].name == "multiply"
    assert first.tool_calls()[0].arguments == {"a": 1231, "b": 2331}
    assert second.prompt.tool_results[0].output == "2869461"


@pytest.mark.vcr
def test_responses_tool_use_streaming(vcr):
    model = llm.get_model("gpt-5.5")

    def multiply(a: int, b: int) -> int:
        "Multiply two numbers."
        return a * b

    chain = model.chain(
        "What is 1231 * 2331? Use the multiply tool.",
        tools=[multiply],
        options={"reasoning_effort": "low"},
        key=API_KEY,
    )
    output = "".join(chain)
    assert "2869461" in output.replace(",", "")
    first, second = chain._responses
    assert first.tool_calls()[0].arguments == {"a": 1231, "b": 2331}


@pytest.mark.vcr
def test_responses_round_trips_encrypted_reasoning(vcr):
    """Reasoning items returned by the API in the first turn must be
    echoed back verbatim on the second turn so the model can pick up
    its hidden chain of thought after the tool result arrives."""
    from llm.parts import ReasoningPart

    model = llm.get_model("gpt-5.5")

    def lookup_population(country: str) -> int:
        "Returns the current population of the specified fictional country."
        return 123124

    def can_have_dragons(population: int) -> bool:
        "Returns True if the specified population can have dragons."
        return population > 10000

    chain = model.chain(
        "Pick a clever country name, look up its population, then check "
        "whether it can have dragons. Be brief.",
        tools=[lookup_population, can_have_dragons],
        stream=False,
        options={"reasoning_effort": "high"},
        key=API_KEY,
    )
    chain.text()  # drain the chain

    first = chain._responses[0]

    # The first response must produce at least one ReasoningPart carrying
    # the opaque encrypted_content + id.
    reasoning_parts = [
        p for m in first.messages() for p in m.parts if isinstance(p, ReasoningPart)
    ]
    assert reasoning_parts, "first turn should expose at least one ReasoningPart"
    pm = reasoning_parts[0].provider_metadata or {}
    assert "openai" in pm
    assert pm["openai"].get("encrypted_content"), "encrypted_content must be captured"
    assert pm["openai"].get("id"), "reasoning id must be captured"

    # The second turn's outgoing input must echo back that reasoning
    # item, otherwise the model loses its chain of thought.
    second = chain._responses[1]
    second_input = (second._prompt_json or {}).get("input") or []
    reasoning_inputs = [it for it in second_input if it.get("type") == "reasoning"]
    assert reasoning_inputs, "second turn must echo a reasoning input item"
    assert reasoning_inputs[0]["encrypted_content"] == pm["openai"]["encrypted_content"]
    assert reasoning_inputs[0]["id"] == pm["openai"]["id"]


@pytest.mark.vcr
def test_responses_interleaved_reasoning_between_tool_calls(vcr):
    """Tool calls during reasoning: each turn produces fresh reasoning AND
    every prior reasoning block is round-tripped on every subsequent turn
    so the model's hidden chain of thought accumulates across the whole
    chain. This is the GPT-5-class capability that the Chat Completions
    API can't deliver because it discards reasoning between turns."""
    from llm.parts import ReasoningPart

    model = llm.get_model("gpt-5.5")

    # Tool whose results force the model to re-plan between calls: each
    # lookup hands the model a NEW key to use next, so the model has to
    # think to figure out the next argument. Parallel tool calls would
    # short-circuit this, so we need the model to reason in series.
    def db_lookup(key: str) -> str:
        "Look up a value by key in the puzzle database."
        table = {
            "start": "Begin with the value 7.",
            "step1_7": "Multiply by 13. Now lookup with key step2_<value>.",
            "step2_91": "Subtract 11. Now lookup with key step3_<value>.",
            "step3_80": ("The answer is the value modulo 9. State only the integer."),
        }
        return table.get(key, "unknown key")

    conversation = model.conversation(tools=[db_lookup])
    conversation.chain_limit = 4
    chain = conversation.chain(
        "Solve this puzzle: call db_lookup('start'), then follow each "
        "instruction step by step. Each lookup tells you the next key "
        "to use. Compute each step in your head. State only the final "
        "integer.",
        stream=False,
        options={"reasoning_effort": "high"},
        key=API_KEY,
    )
    # The chain may exceed the limit - we just want enough turns to
    # observe interleaved reasoning, then we stop.
    try:
        chain.text()
    except ValueError as e:
        if "Chain limit" not in str(e):
            raise

    responses = chain._responses
    assert (
        len(responses) >= 3
    ), f"expected at least 3 chained turns, got {len(responses)}"

    # 1) Fresh reasoning happens on more than just the first turn. This is
    #    the actual interleaved-reasoning capability, not just round-trip.
    reasoning_token_counts = []
    for r in responses:
        u = r.usage()
        details = (u.details if u else None) or {}
        reasoning_token_counts.append(
            (details.get("output_tokens_details") or {}).get("reasoning_tokens") or 0
        )
    turns_with_fresh_reasoning = sum(1 for n in reasoning_token_counts if n > 0)
    assert turns_with_fresh_reasoning >= 2, (
        f"expected >=2 turns to produce fresh reasoning, got "
        f"{turns_with_fresh_reasoning} (counts: {reasoning_token_counts})"
    )

    # 2) Every reasoning block produced earlier in the chain is round-
    #    tripped on every subsequent turn. The Nth turn's outgoing input
    #    must contain at least N-1 reasoning items.
    for i in range(1, len(responses)):
        outgoing = (responses[i]._prompt_json or {}).get("input") or []
        reasoning_count = sum(1 for it in outgoing if it.get("type") == "reasoning")
        # encrypted_content + id are non-empty on each one
        for it in outgoing:
            if it.get("type") == "reasoning":
                assert it.get("encrypted_content"), "encrypted_content lost"
                assert it.get("id"), "reasoning id lost"
        assert (
            reasoning_count >= i
        ), f"turn {i} must echo >= {i} reasoning items, got {reasoning_count}"

    # 3) The captured ReasoningParts on the assistant messages carry the
    #    opaque metadata that was actually echoed back on the wire.
    for i, r in enumerate(responses[:-1]):
        rparts = [
            p for m in r.messages() for p in m.parts if isinstance(p, ReasoningPart)
        ]
        if reasoning_token_counts[i] > 0:
            assert rparts, (
                f"turn {i} produced reasoning_tokens={reasoning_token_counts[i]} "
                "but no ReasoningPart was persisted"
            )
            for rp in rparts:
                pm = (rp.provider_metadata or {}).get("openai") or {}
                assert pm.get(
                    "encrypted_content"
                ), "ReasoningPart missing encrypted_content"
