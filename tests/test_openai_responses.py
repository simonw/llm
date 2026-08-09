"""Tests for the /v1/responses code path in the default OpenAI plugin."""

import json
import os

import pytest
from pytest_httpx import IteratorStream

import llm
from llm.default_plugins.openai_models import CodeInterpreter, Responses, WebSearch

API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


def _text_response_json(model="gpt-5.6-luna", text="ok"):
    return {
        "id": "resp_server_tool",
        "object": "response",
        "created_at": 1,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_server_tool",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "status": "completed",
    }


@pytest.mark.parametrize(
    ("tool", "expected"),
    (
        (
            CodeInterpreter(),
            {"type": "code_interpreter", "container": {"type": "auto"}},
        ),
        (
            CodeInterpreter(memory_limit="4g", file_ids=["file-1", "file-2"]),
            {
                "type": "code_interpreter",
                "container": {
                    "type": "auto",
                    "memory_limit": "4g",
                    "file_ids": ["file-1", "file-2"],
                },
            },
        ),
        (
            CodeInterpreter(container="cntr_123"),
            {"type": "code_interpreter", "container": "cntr_123"},
        ),
    ),
)
def test_code_interpreter_tool_spec(tool, expected):
    assert tool.tool_spec(llm.get_model("gpt-5.6-luna")) == expected


def test_code_interpreter_validates_container_configuration():
    with pytest.raises(ValueError, match="memory_limit"):
        CodeInterpreter(memory_limit="8g")
    with pytest.raises(ValueError, match="cannot be combined"):
        CodeInterpreter(container="cntr_123", memory_limit="4g")
    with pytest.raises(ValueError, match="cannot be combined"):
        CodeInterpreter(container="cntr_123", file_ids=["file-1"])
    with pytest.raises(TypeError, match="container must be a string"):
        CodeInterpreter(container={"type": "auto"})


def test_code_interpreter_prepare_request_is_additive_and_idempotent():
    tool = CodeInterpreter()
    kwargs = {"include": ["reasoning.encrypted_content"]}

    tool.prepare_request(llm.get_model("gpt-5.6-luna"), kwargs)
    tool.prepare_request(llm.get_model("gpt-5.6-luna"), kwargs)

    assert kwargs == {
        "include": [
            "reasoning.encrypted_content",
            "code_interpreter_call.outputs",
        ]
    }


@pytest.mark.parametrize(
    ("tool", "expected"),
    (
        (WebSearch(), {"type": "web_search"}),
        (
            WebSearch(
                allowed_domains=["openai.com"],
                blocked_domains=["example.com"],
                user_location={"country": "GB", "city": "London"},
                search_context_size="high",
                external_web_access=False,
                return_token_budget="unlimited",
                search_content_types=["image", "text"],
                image_settings={"max_results": 3, "caption": True},
            ),
            {
                "type": "web_search",
                "filters": {
                    "allowed_domains": ["openai.com"],
                    "blocked_domains": ["example.com"],
                },
                "user_location": {
                    "type": "approximate",
                    "country": "GB",
                    "city": "London",
                },
                "search_context_size": "high",
                "external_web_access": False,
                "return_token_budget": "unlimited",
                "search_content_types": ["image", "text"],
                "image_settings": {"max_results": 3, "caption": True},
            },
        ),
    ),
)
def test_web_search_tool_spec(tool, expected):
    assert tool.tool_spec(llm.get_model("gpt-5.6-luna")) == expected


@pytest.mark.parametrize(
    ("kwargs", "error"),
    (
        ({"search_context_size": "huge"}, "search_context_size"),
        ({"return_token_budget": "lots"}, "return_token_budget"),
        ({"search_content_types": ["video"]}, "search_content_types"),
        ({"allowed_domains": ["https://openai.com"]}, "scheme"),
        ({"allowed_domains": [f"example{i}.com" for i in range(101)]}, "100"),
        ({"user_location": {"type": "exact"}}, "approximate"),
        ({"external_web_access": "no"}, "external_web_access"),
        ({"image_settings": {"max_results": 0}}, "max_results"),
        ({"image_settings": {"caption": "yes"}}, "caption"),
    ),
)
def test_web_search_validates_configuration(kwargs, error):
    with pytest.raises((TypeError, ValueError), match=error):
        WebSearch(**kwargs)


def test_web_search_prepare_request_is_additive_and_idempotent():
    tool = WebSearch(include_sources=True, include_results=True)
    kwargs = {"include": ["reasoning.encrypted_content"]}

    tool.prepare_request(llm.get_model("gpt-5.6-luna"), kwargs)
    tool.prepare_request(llm.get_model("gpt-5.6-luna"), kwargs)

    assert kwargs == {
        "include": [
            "reasoning.encrypted_content",
            "web_search_call.action.sources",
            "web_search_call.results",
        ]
    }
    default_kwargs = {}
    WebSearch().prepare_request(llm.get_model("gpt-5.6-luna"), default_kwargs)
    assert default_kwargs == {}


def test_responses_web_search_request_and_result_capture(httpx_mock):
    sources = [
        {"type": "url", "url": "https://openai.com/news/"},
        {"type": "url", "url": "https://example.com/report"},
    ]
    results = [
        {
            "type": "image_result",
            "image_url": "https://example.com/image.jpg",
            "source_website_url": "https://example.com/report",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "caption": "An example image",
        }
    ]
    response_json = _text_response_json(text="A cited answer")
    response_json["output"].insert(
        0,
        {
            "type": "web_search_call",
            "id": "ws_123",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "OpenAI news",
                "queries": ["OpenAI news"],
                "sources": sources,
            },
            "results": results,
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json=response_json,
        headers={"Content-Type": "application/json"},
    )

    response = llm.get_model("gpt-5.6-luna").prompt(
        "Search for OpenAI news",
        tools=[
            WebSearch(
                allowed_domains=["openai.com"],
                include_sources=True,
                include_results=True,
            )
        ],
        stream=False,
        key="test",
    )

    assert response.text() == "A cited answer"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"] == [
        {
            "type": "web_search",
            "filters": {"allowed_domains": ["openai.com"]},
        }
    ]
    assert request_body["include"] == [
        "reasoning.encrypted_content",
        "web_search_call.action.sources",
        "web_search_call.results",
    ]
    message = response.messages()[0]
    assert [type(part).__name__ for part in message.parts] == [
        "ToolCallPart",
        "ToolResultPart",
        "TextPart",
    ]
    assert message.parts[0].server_executed
    assert message.parts[0].arguments["sources"] == sources
    assert message.parts[1].server_executed
    assert json.loads(message.parts[1].output) == results


def test_server_side_prepare_request_runs_in_list_order_after_baseline():
    class IncludeMarker(CodeInterpreter):
        def __init__(self, marker):
            super().__init__()
            self.marker = marker

        def tool_spec(self, model):
            return {"type": f"marker_{self.marker}"}

        def prepare_request(self, model, kwargs):
            assert kwargs["store"] is False
            assert len(kwargs["tools"]) == 2
            kwargs.setdefault("include", []).append(self.marker)

    model = llm.get_model("gpt-5.6-luna")

    class FakePrompt:
        pass

    prompt = FakePrompt()
    prompt.options = model.Options()
    prompt.tools = [IncludeMarker("first"), IncludeMarker("second")]
    prompt.schema = None
    prompt.hide_reasoning = False

    kwargs = model._finalize_responses_kwargs(
        prompt, stream=False, instructions="Be useful"
    )
    assert kwargs["instructions"] == "Be useful"
    assert kwargs["include"] == [
        "reasoning.encrypted_content",
        "first",
        "second",
    ]


def test_responses_mixes_function_and_code_interpreter_tools(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json=_text_response_json(),
        headers={"Content-Type": "application/json"},
    )

    def multiply(a: int, b: int) -> int:
        return a * b

    model = llm.get_model("gpt-5.6-luna")
    response = model.prompt(
        "Calculate 111 * 333 using the python tool",
        tools=[multiply, CodeInterpreter(memory_limit="4g")],
        stream=False,
        key="test",
    )
    assert response.text() == "ok"

    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"][0]["type"] == "function"
    assert request_body["tools"][0]["name"] == "multiply"
    assert request_body["tools"][1] == {
        "type": "code_interpreter",
        "container": {"type": "auto", "memory_limit": "4g"},
    }
    assert request_body["include"] == [
        "reasoning.encrypted_content",
        "code_interpreter_call.outputs",
    ]


def test_responses_raw_server_tool_passthrough_on_custom_endpoint(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://example.test/v1/responses",
        json=_text_response_json(model="custom-model"),
        headers={"Content-Type": "application/json"},
    )
    model = Responses(
        "custom-model",
        api_base="https://example.test/v1",
        supports_tools=False,
    )
    raw_spec = {"type": "browser_search", "depth": "deep"}
    response = model.prompt(
        "Search", tools=[llm.ServerSideTool(raw_spec)], stream=False, key="test"
    )

    assert response.text() == "ok"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"] == [raw_spec]


@pytest.mark.parametrize("tool", (CodeInterpreter(), WebSearch()))
def test_server_side_tool_rejected_by_chat_and_chat_fallback(tool):
    from llm.default_plugins.openai_models import Chat

    chat = Chat("chat-model", supports_tools=True)
    with pytest.raises(ValueError, match="llm tools -m chat-model"):
        chat.prompt("Use a server-side tool", tools=[tool])

    responses_model = llm.get_model("gpt-5.6-luna")
    response = responses_model.prompt(
        "Use a server-side tool",
        tools=[tool],
        chat_completions=True,
        key="test",
    )
    with pytest.raises(ValueError, match="llm tools -m gpt-5.6-luna"):
        response.text()


@pytest.mark.asyncio
async def test_async_responses_code_interpreter_request(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json=_text_response_json(),
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_async_model("gpt-5.6-luna")
    response = model.prompt(
        "Calculate",
        tools=[CodeInterpreter(file_ids=["file-1"])],
        stream=False,
        key="test",
    )

    assert await response.text() == "ok"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"] == [
        {
            "type": "code_interpreter",
            "container": {"type": "auto", "file_ids": ["file-1"]},
        }
    ]
    assert request_body["include"] == [
        "reasoning.encrypted_content",
        "code_interpreter_call.outputs",
    ]


@pytest.mark.asyncio
async def test_async_responses_web_search_request(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json=_text_response_json(),
        headers={"Content-Type": "application/json"},
    )
    response = llm.get_async_model("gpt-5.6-luna").prompt(
        "Search",
        tools=[WebSearch(external_web_access=False, include_sources=True)],
        stream=False,
        key="test",
    )

    assert await response.text() == "ok"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["tools"] == [
        {"type": "web_search", "external_web_access": False}
    ]
    assert request_body["include"] == [
        "reasoning.encrypted_content",
        "web_search_call.action.sources",
    ]


def _responses_sse(event_type, data):
    data = {"type": event_type, **data}
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode()


def _code_interpreter_stream():
    yield _responses_sse(
        "response.output_item.added",
        {
            "output_index": 0,
            "item": {
                "id": "ci_stream",
                "type": "code_interpreter_call",
                "status": "in_progress",
                "container_id": "cntr_stream",
                "code": "",
                "outputs": [],
            },
        },
    )
    yield _responses_sse(
        "response.output_item.done",
        {
            "output_index": 0,
            "item": {
                "id": "ci_stream",
                "type": "code_interpreter_call",
                "status": "completed",
                "container_id": "cntr_stream",
                "code": "print(6 * 7)",
                "outputs": [{"type": "logs", "logs": "42\n"}],
            },
        },
    )
    yield _responses_sse(
        "response.output_item.added",
        {
            "output_index": 1,
            "item": {
                "id": "msg_stream",
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        },
    )
    yield _responses_sse(
        "response.output_text.delta",
        {
            "item_id": "msg_stream",
            "output_index": 1,
            "content_index": 0,
            "delta": "42",
        },
    )


def _web_search_refresh_stream():
    def image_result(name):
        return {
            "type": "image_result",
            "image_url": f"https://example.com/{name}.jpg",
            "source_website_url": f"https://example.com/{name}",
            "thumbnail_url": f"https://example.com/{name}-thumb.jpg",
            "caption": f"{name.title()} image",
        }

    def web_search_item(sources, results):
        return {
            "id": "ws_stream",
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "example images",
                "queries": ["example images"],
                "sources": sources,
            },
            "results": results,
        }

    partial_sources = [{"type": "url", "url": "https://example.com/first"}]
    final_sources = partial_sources + [
        {"type": "url", "url": "https://example.com/second"},
    ]
    partial_results = [image_result("first")]
    final_results = partial_results + [image_result("second")]
    yield _responses_sse(
        "response.output_item.done",
        {
            "output_index": 0,
            "item": web_search_item(partial_sources, partial_results),
        },
    )
    yield _responses_sse(
        "response.output_text.delta",
        {
            "item_id": "msg_stream",
            "output_index": 1,
            "content_index": 0,
            "delta": "done",
        },
    )
    response_json = _text_response_json(text="done")
    response_json["output"].insert(0, web_search_item(final_sources, final_results))
    yield _responses_sse(
        "response.completed",
        {"response": response_json},
    )


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
    from llm.default_plugins.openai_models import Chat

    model = llm.get_model("gpt-5.5")
    assert "Responses" in type(model).__name__
    # The chat_completions opt-out option must be exposed.
    assert "chat_completions" in model.Options.model_fields
    assert "reasoning_summary" in model.Options.model_fields
    assert "reasoning_summary" in llm.get_async_model("gpt-5.5").Options.model_fields
    assert (
        "reasoning_summary"
        not in Chat("reasoning-chat-model", reasoning=True).Options.model_fields
    )


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
    response = model.prompt(
        "hello",
        stream=False,
        chat_completions=True,
        reasoning_summary="detailed",
        key="test",
    )
    assert response.text() == "hi from chat"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert "reasoning_summary" not in request_body


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
        messages = (
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
        )

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
        messages = (
            Message(role="user", parts=[TextPart(text="hello")]),
            Message(role="assistant", parts=[TextPart(text="first-ok")]),
            Message(role="user", parts=[TextPart(text="what next?")]),
        )

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


@pytest.mark.parametrize("reasoning_summary", ("auto", "concise", "detailed"))
def test_responses_kwargs_explicit_reasoning_summary(reasoning_summary):
    model = llm.get_model("gpt-5.5")
    options = model.Options(reasoning_summary=reasoning_summary)

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert kwargs["reasoning"] == {"summary": reasoning_summary}


def test_async_responses_kwargs_explicit_reasoning_summary():
    model = llm.get_async_model("gpt-5.5")
    options = model.Options(reasoning_summary="concise")

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert kwargs["reasoning"] == {"summary": "concise"}


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


def test_responses_kwargs_omits_explicit_reasoning_summary_when_hide_reasoning():
    model = llm.get_model("gpt-5.5")
    options = model.Options(reasoning_summary="detailed")

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    p.hide_reasoning = True
    kwargs = model._finalize_responses_kwargs(p, stream=False)
    assert "reasoning" not in kwargs
    assert kwargs["include"] == ["reasoning.encrypted_content"]


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


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("gpt-5.6-sol", True),
        ("gpt-5.6-terra", True),
        ("gpt-5.6-luna", True),
        ("gpt-5.5", True),
        ("gpt-4o", True),
        # The legacy /v1/completions endpoint does not accept service_tier
        ("gpt-3.5-turbo-instruct", False),
    ],
)
def test_service_tier_option_on_models(model_id, expected):
    model = llm.get_model(model_id)
    assert ("service_tier" in model.Options.model_fields) == expected


def test_responses_kwargs_includes_service_tier():
    model = llm.get_model("gpt-5.6-sol")
    options = model.Options(service_tier="fast")

    class FakePrompt:
        pass

    p = FakePrompt()
    p.options = options
    p.tools = []
    p.schema = None
    kwargs = model._build_responses_kwargs(p, stream=False)
    assert kwargs["service_tier"] == "fast"


def test_service_tier_sent_to_responses_endpoint(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_test_1",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.6-sol",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "fast reply",
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
            "service_tier": "priority",
        },
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_model("gpt-5.6-sol")
    response = model.prompt("hello", stream=False, service_tier="fast", key="test")
    assert response.text() == "fast reply"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["service_tier"] == "fast"
    # The response body reports the tier that actually processed the request
    assert response.json()["service_tier"] == "priority"


def test_service_tier_sent_to_chat_completions_fallback(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        json={
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "model": "gpt-5.6-sol",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "fast chat"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_model("gpt-5.6-sol")
    response = model.prompt(
        "hello", stream=False, chat_completions=True, service_tier="fast", key="test"
    )
    assert response.text() == "fast chat"
    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert request_body["service_tier"] == "fast"


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
    first, _second = chain._responses
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


def _responses_reasoning_refresh_stream():
    """Reasoning stream whose final payload carries a different ciphertext.

    OpenAI encrypts reasoning per event, so ``output_item.done`` and the
    ``response.completed`` payload hold different encrypted_content for
    the same reasoning item.
    """
    yield from _responses_reasoning_summary_stream()
    yield _responses_sse(
        "response.completed",
        {
            "response": {
                "id": "resp_1",
                "object": "response",
                "created_at": 1700000000,
                "model": "gpt-5.5",
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "rs_1",
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "Thinking aloud"}],
                        "encrypted_content": "encrypted-final",
                        "status": "completed",
                    },
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "done", "annotations": []}
                        ],
                    },
                ],
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 1},
                },
            },
            "sequence_number": 5,
        },
    )


def test_responses_reasoning_metadata_refreshed_from_final_payload(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        stream=IteratorStream(_responses_reasoning_refresh_stream()),
        headers={"Content-Type": "text/event-stream"},
    )

    model = llm.get_model("gpt-5.5")
    response = model.prompt("hello", key="test")
    assert response.text() == "done"

    reasoning_parts = [
        p
        for m in response.messages()
        for p in m.parts
        if isinstance(p, llm.parts.ReasoningPart)
    ]
    # One reasoning part - the refresh merged into it rather than
    # growing a second one - and it carries the final payload's
    # ciphertext, the same string response_json holds.
    assert len(reasoning_parts) == 1
    metadata = reasoning_parts[0].provider_metadata["openai"]
    assert metadata["encrypted_content"] == "encrypted-final"
    payload_item = response.response_json["output"][0]
    assert payload_item["encrypted_content"] == "encrypted-final"
    assert reasoning_parts[0].text == "Thinking aloud"


def test_code_interpreter_multi_message_response(httpx_mock):
    """Server-side tool execution interleaving multiple message output
    items must assemble into multiple assistant Messages."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        json={
            "id": "resp_multi",
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
                        {"type": "output_text", "text": "STEP ONE", "annotations": []}
                    ],
                },
                {
                    "type": "code_interpreter_call",
                    "id": "ci_1",
                    "status": "completed",
                    "container_id": "cntr_1",
                    "code": "print(111*111)",
                    "outputs": [{"type": "logs", "logs": "12321\n"}],
                },
                {
                    "type": "message",
                    "id": "msg_2",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "DONE 12321", "annotations": []}
                    ],
                },
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            "status": "completed",
        },
        headers={"Content-Type": "application/json"},
    )
    model = llm.get_model("gpt-5.5")
    response = model.prompt("count", stream=False, key="test")
    response.text()

    messages = response.messages()
    assert len(messages) == 2
    first, second = messages
    assert [type(p).__name__ for p in first.parts] == [
        "TextPart",
        "ToolCallPart",
        "ToolResultPart",
    ]
    assert first.parts[0].text == "STEP ONE"
    assert first.parts[1].name == "code_interpreter"
    assert first.parts[1].arguments == {"code": "print(111*111)"}
    assert first.parts[1].server_executed
    assert first.parts[2].output == "12321\n"
    assert first.parts[2].server_executed
    assert [type(p).__name__ for p in second.parts] == ["TextPart"]
    assert second.parts[0].text == "DONE 12321"

    # Server-executed calls are not locally executable
    assert response.tool_calls() == []


def test_code_interpreter_streaming_output_and_request(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        stream=IteratorStream(_code_interpreter_stream()),
        headers={"Content-Type": "text/event-stream"},
    )
    model = llm.get_model("gpt-5.6-luna")
    response = model.prompt("Calculate", tools=[CodeInterpreter()], key="test")

    events = list(response.stream_events())
    assert [(event.type, event.chunk) for event in events] == [
        ("tool_call_name", "code_interpreter"),
        ("tool_call_args", json.dumps({"code": "print(6 * 7)"})),
        ("tool_result", "42\n"),
        ("text", "42"),
    ]
    assert all(event.server_executed for event in events[:3])
    assert response.tool_calls() == []

    request_body = json.loads(httpx_mock.get_requests()[-1].content)
    assert "code_interpreter_call.outputs" in request_body["include"]


def _assert_web_search_streaming_uses_final_payload(response, messages):
    parts = [part for message in messages for part in message.parts]
    server_parts = [
        part
        for part in parts
        if isinstance(part, (llm.parts.ToolCallPart, llm.parts.ToolResultPart))
    ]
    assert [type(part).__name__ for part in server_parts] == [
        "ToolCallPart",
        "ToolResultPart",
    ]
    tool_call, tool_result = server_parts
    final_item = next(
        item
        for item in response.response_json["output"]
        if item["type"] == "web_search_call"
    )
    assert len(final_item["action"]["sources"]) == 2
    assert len(final_item["results"]) == 2
    assert tool_call.arguments == final_item["action"]
    assert json.loads(tool_result.output) == final_item["results"]


def test_web_search_streaming_refreshes_from_final_payload(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        stream=IteratorStream(_web_search_refresh_stream()),
        headers={"Content-Type": "text/event-stream"},
    )
    response = llm.get_model("gpt-5.6-luna").prompt(
        "Search",
        tools=[WebSearch(include_sources=True, include_results=True)],
        key="test",
    )

    assert response.text() == "done"
    _assert_web_search_streaming_uses_final_payload(response, response.messages())


@pytest.mark.asyncio
async def test_async_web_search_streaming_refreshes_from_final_payload(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.openai.com/v1/responses",
        stream=IteratorStream(_web_search_refresh_stream()),
        headers={"Content-Type": "text/event-stream"},
    )
    response = llm.get_async_model("gpt-5.6-luna").prompt(
        "Search",
        tools=[WebSearch(include_sources=True, include_results=True)],
        key="test",
    )

    assert await response.text() == "done"
    _assert_web_search_streaming_uses_final_payload(response, await response.messages())


def test_server_tool_parts_not_replayed_as_function_calls():
    from llm.parts import Message, TextPart, ToolCallPart, ToolResultPart

    model = llm.get_model("gpt-5.5")

    class FakePrompt:
        messages = (
            Message(role="user", parts=[TextPart(text="count")]),
            Message(
                role="assistant",
                parts=[
                    TextPart(text="STEP ONE"),
                    ToolCallPart(
                        name="code_interpreter",
                        arguments={"code": "print(1)"},
                        tool_call_id="ci_1",
                        server_executed=True,
                    ),
                    ToolResultPart(
                        name="code_interpreter",
                        output="1\n",
                        tool_call_id="ci_1",
                        server_executed=True,
                    ),
                ],
            ),
            Message(role="assistant", parts=[TextPart(text="DONE")]),
            Message(role="user", parts=[TextPart(text="thanks")]),
        )

    items, _instructions = model._build_responses_input(FakePrompt())
    assert items == [
        {"role": "user", "content": "count"},
        {"role": "assistant", "content": "STEP ONE"},
        {"role": "assistant", "content": "DONE"},
        {"role": "user", "content": "thanks"},
    ]
