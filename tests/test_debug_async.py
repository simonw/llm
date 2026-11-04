import json

import httpx2
import openai
import pytest
from pytest_httpx2 import IteratorStream

from llm.default_plugins.openai_models import AsyncChat, AsyncResponses, Chat


@pytest.mark.asyncio
@pytest.mark.parametrize("model_class", [AsyncChat, AsyncResponses])
@pytest.mark.parametrize("debug", [False, True])
async def test_async_debug_client_type(monkeypatch, model_class, debug):
    if debug:
        monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    else:
        monkeypatch.delenv("LLM_OPENAI_SHOW_RESPONSES", raising=False)
    client = model_class("local-debug").get_client("synthetic-key", async_=True)
    try:
        assert isinstance(client._client, httpx2.AsyncClient)
    finally:
        await client.close()


@pytest.mark.parametrize("debug", [False, True])
def test_sync_debug_client_type_unchanged(monkeypatch, debug):
    if debug:
        monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    else:
        monkeypatch.delenv("LLM_OPENAI_SHOW_RESPONSES", raising=False)
    with Chat("local-debug").get_client("synthetic-key") as client:
        assert isinstance(client._client, httpx2.Client)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_async_debug_prompt(monkeypatch, httpx2_mock, capsys, stream):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    message = {"role": "assistant", "content": "你好 👋"}
    if stream:
        payload = {
            "id": "chatcmpl-debug",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "local-debug",
            "choices": [{"index": 0, "delta": message, "finish_reason": "stop"}],
        }
        body = (
            "data: " + json.dumps(payload, ensure_ascii=False) + "\n\ndata: [DONE]\n\n"
        ).encode()
        content_type = "text/event-stream"
    else:
        payload = {
            "id": "chatcmpl-debug",
            "object": "chat.completion",
            "created": 1,
            "model": "local-debug",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        content_type = "application/json"
    httpx2_mock.add_response(
        url="https://debug.example/v1/chat/completions",
        headers={"Content-Type": content_type},
        stream=IteratorStream([body[i : i + 1] for i in range(len(body))]),
    )
    model = AsyncChat(
        "local-debug", model_name="local-debug", api_base="https://debug.example/v1"
    )
    response = model.prompt("hi", key="synthetic-key", stream=stream)
    assert await response.text() == "你好 👋"
    request = httpx2_mock.get_request()
    assert "accept-encoding" not in request.headers
    output = capsys.readouterr().err
    assert '"content": "你好 👋"' in output
    assert "synthetic-key" not in output


class TrackingTransport(httpx2.AsyncBaseTransport):
    def __init__(self, content=b"ok", status_code=200):
        self.content = content
        self.status_code = status_code
        self.close_count = 0

    async def handle_async_request(self, request):
        if isinstance(self.content, httpx2.AsyncByteStream):
            return httpx2.Response(self.status_code, stream=self.content)
        return httpx2.Response(self.status_code, content=self.content)

    async def aclose(self):
        self.close_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_error", [False, True])
async def test_async_debug_transport_closes(monkeypatch, raise_error):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    transport = TrackingTransport()
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda: transport)
    client = AsyncChat("local-debug").get_client("synthetic-key", async_=True)
    try:
        async with client:
            response = await client._client.get("https://debug.example/body")
            assert response.content == b"ok"
            if raise_error:
                raise ValueError("synthetic failure")
    except ValueError:
        assert raise_error
    await client.close()
    assert transport.close_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"ascii", b"invalid\xff", b"partial\xe4\xbd"])
async def test_async_debug_preserves_response_bytes(monkeypatch, body, capsys):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    transport = TrackingTransport(body)
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda: transport)
    async with AsyncChat("local-debug").get_client(
        "synthetic-key", async_=True
    ) as client:
        response = await client._client.get("https://debug.example/body")
    assert response.content == body
    assert capsys.readouterr().err.endswith(
        body.decode("utf-8", errors="replace") + "\n"
    )


class TrackingStream(httpx2.AsyncByteStream):
    def __init__(self, chunks=None):
        self.close_count = 0
        self.pull_count = 0
        self.chunks = chunks if chunks is not None else [b"first", b"second"]

    async def __aiter__(self):
        for chunk in self.chunks:
            self.pull_count += 1
            yield chunk

    async def aclose(self):
        self.close_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [False, True])
async def test_async_debug_partial_iterator_closes(monkeypatch, debug):
    from llm.utils import async_logging_client

    body = TrackingStream()
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, stream=body))
    if debug:
        monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda: transport)
        client = async_logging_client()
    else:
        client = httpx2.AsyncClient(transport=transport)
    async with client:
        response = await client.send(
            client.build_request("GET", "https://debug.example/body"), stream=True
        )
        iterator = response.aiter_bytes()
        assert await anext(iterator) == b"first"
        await iterator.aclose()
        assert response.is_closed
        assert body.close_count == 1
        assert body.pull_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model_class", [AsyncChat, AsyncResponses])
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_async_debug_prompt_closes_client(monkeypatch, model_class, fail, stream):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    if fail:
        payload = {
            "error": {"message": "synthetic failure", "type": "invalid_request_error"}
        }
    elif model_class is AsyncChat:
        payload = {
            "id": "chatcmpl-debug",
            "object": "chat.completion",
            "created": 1,
            "model": "local-debug",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
    else:
        payload = {
            "id": "resp_debug",
            "object": "response",
            "created_at": 1,
            "model": "local-debug",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_debug",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "ok", "annotations": []}
                    ],
                }
            ],
        }
    if stream and not fail:
        body = streaming_body(model_class, payload)
    else:
        body = json.dumps(payload).encode()
    transport = TrackingTransport(body, 400 if fail else 200)
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda: transport)
    model = model_class(
        "local-debug", model_name="local-debug", api_base="https://debug.example/v1"
    )
    response = model.prompt("hi", key="synthetic-key", stream=stream)
    if fail:
        with pytest.raises(openai.BadRequestError):
            await response.text()
    else:
        assert await response.text() == "ok"
    assert transport.close_count == 1


def streaming_body(model_class, payload=None):
    if model_class is AsyncChat:
        event = {
            "id": "chatcmpl-debug",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "local-debug",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
        return ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode()
    event = {
        "type": "response.output_text.delta",
        "delta": "ok",
        "sequence_number": 0,
        "item_id": "msg_debug",
        "output_index": 0,
        "content_index": 0,
    }
    completed = {
        "type": "response.completed",
        "response": payload or {},
        "sequence_number": 1,
    }
    return (
        "data: " + json.dumps(event) + "\n\ndata: " + json.dumps(completed) + "\n\n"
    ).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class,options",
    [
        (AsyncChat, {}),
        (AsyncResponses, {}),
        (AsyncResponses, {"chat_completions": True}),
    ],
)
async def test_async_debug_early_event_close(monkeypatch, model_class, options):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    body = TrackingStream(
        [streaming_body(AsyncChat if options else model_class), b"unread"]
    )
    transport = TrackingTransport(body)
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda: transport)
    model = model_class(
        "local-debug", model_name="local-debug", api_base="https://debug.example/v1"
    )
    response = model.prompt("hi", key="synthetic-key", stream=True, **options)
    events = response.astream_events()
    assert (await anext(events)).chunk == "ok"
    await events.aclose()
    assert body.close_count == 1
    assert body.pull_count == 1
    assert transport.close_count == 1


@pytest.mark.asyncio
async def test_async_debug_preserves_sdk_defaults(monkeypatch):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    debug_client = AsyncChat("local-debug").get_client("synthetic-key", async_=True)
    monkeypatch.delenv("LLM_OPENAI_SHOW_RESPONSES")
    regular_client = AsyncChat("local-debug").get_client("synthetic-key", async_=True)
    try:
        assert debug_client.timeout == regular_client.timeout
        assert (
            debug_client._client.follow_redirects
            == regular_client._client.follow_redirects
        )
    finally:
        await debug_client.close()
        await regular_client.close()
