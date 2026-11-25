import json

import pytest
from pytest_httpx2 import IteratorStream

import llm
from llm.default_plugins.openai_models import Completion

API_KEY = "badkey"


def _chat_stream(model):
    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"content": "hello"}, "finish_reason": "stop"}
            ],
        },
    ]
    for chunk in chunks:
        yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def _responses_payload(model):
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "hello", "annotations": []}
                ],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "status": "completed",
    }


def _responses_stream(model):
    payload = _responses_payload(model)
    events = [
        (
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "hello"},
        ),
        ("response.completed", {"type": "response.completed", "response": payload}),
    ]
    for name, data in events:
        yield f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def _completion_stream(model):
    chunk = {
        "id": "cmpl-1",
        "object": "text_completion",
        "created": 1700000000,
        "model": model,
        "choices": [{"index": 0, "text": "hello", "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize(
    ("returned_model", "expected"),
    (
        ("gpt-4o-mini-2024-07-18", "gpt-4o-mini-2024-07-18"),
        ("gpt-4o-mini", None),
        ("", None),
        (None, None),
    ),
)
async def test_chat_resolved_model(
    httpx2_mock, async_, stream, returned_model, expected
):
    if stream:
        httpx2_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            headers={"content-type": "text/event-stream"},
            stream=IteratorStream(_chat_stream(returned_model)),
        )
    else:
        body = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1700000000,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
        }
        if returned_model is not None:
            body["model"] = returned_model
        httpx2_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            json=body,
        )

    if async_:
        model = llm.get_async_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY, stream=stream)
        assert await response.text() == "hello"
    else:
        model = llm.get_model("gpt-4o-mini")
        response = model.prompt("hi", key=API_KEY, stream=stream)
        assert response.text() == "hello"

    assert response.resolved_model == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize(
    ("returned_model", "expected"),
    (
        ("gpt-5.6-luna-2026-09-01", "gpt-5.6-luna-2026-09-01"),
        ("gpt-5.6-luna", None),
    ),
)
async def test_responses_resolved_model(
    httpx2_mock, async_, stream, returned_model, expected
):
    if stream:
        httpx2_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            headers={"content-type": "text/event-stream"},
            stream=IteratorStream(_responses_stream(returned_model)),
        )
    else:
        httpx2_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/responses",
            json=_responses_payload(returned_model),
        )

    if async_:
        model = llm.get_async_model("gpt-5.6-luna")
        response = model.prompt("hi", key=API_KEY, stream=stream)
        assert await response.text() == "hello"
    else:
        model = llm.get_model("gpt-5.6-luna")
        response = model.prompt("hi", key=API_KEY, stream=stream)
        assert response.text() == "hello"

    assert response.resolved_model == expected


@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize(
    ("returned_model", "expected"),
    (
        ("gpt-3.5-turbo-instruct-0914", "gpt-3.5-turbo-instruct-0914"),
        ("gpt-3.5-turbo-instruct", None),
    ),
)
def test_completion_resolved_model(httpx2_mock, stream, returned_model, expected):
    if stream:
        httpx2_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/completions",
            headers={"content-type": "text/event-stream"},
            stream=IteratorStream(_completion_stream(returned_model)),
        )
    else:
        httpx2_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/completions",
            json={
                "id": "cmpl-1",
                "object": "text_completion",
                "created": 1700000000,
                "model": returned_model,
                "choices": [{"index": 0, "text": "hello", "finish_reason": "stop"}],
            },
        )

    model = Completion("gpt-3.5-turbo-instruct")
    response = model.prompt("hi", key=API_KEY, stream=stream)
    assert response.text() == "hello"
    assert response.resolved_model == expected
