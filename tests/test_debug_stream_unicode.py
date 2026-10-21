import json

import pytest
from pytest_httpx2 import IteratorStream

from llm.default_plugins.openai_models import Chat
from llm.utils import _LogResponse


@pytest.mark.parametrize("stream", [False, True])
def test_debug_openai_response_split_utf8(monkeypatch, httpx2_mock, capsys, stream):
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
    model = Chat(
        "local-debug", model_name="local-debug", api_base="https://debug.example/v1"
    )
    response = model.prompt("hi", key="test-key", stream=stream)
    assert response.text() == "你好 👋"
    assert '"content": "你好 👋"' in capsys.readouterr().err


@pytest.mark.parametrize("body", [b"ascii", b"invalid\xff", b"partial\xe4\xbd"])
def test_debug_logging_preserves_raw_bytes(body, capsys):
    response = _LogResponse(
        200, stream=IteratorStream([body[i : i + 1] for i in range(len(body))])
    )
    try:
        assert b"".join(response.iter_bytes()) == body
    finally:
        response.close()
    assert capsys.readouterr().err == body.decode("utf-8", errors="replace") + "\n"
