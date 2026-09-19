import json

import pytest
from pytest_httpx2 import IteratorStream

from llm.default_plugins.openai_models import (
    AsyncChat,
    AsyncResponses,
    Chat,
    Completion,
    Responses,
)


def mock_response(httpx2_mock, model_class, stream, reported_model):
    is_responses = issubclass(model_class, (Responses, AsyncResponses))
    is_completion = issubclass(model_class, Completion)
    endpoint = (
        "responses"
        if is_responses
        else "completions" if is_completion else "chat/completions"
    )
    payload = {"id": "response-1", "model": reported_model}
    if reported_model is None:
        payload.pop("model")
    if is_responses:
        payload.update(
            object="response",
            created_at=1,
            status="completed",
            output=[
                {
                    "type": "message",
                    "id": "message-1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "ok", "annotations": []}
                    ],
                }
            ],
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )
    else:
        choice = {"index": 0, "finish_reason": "stop"}
        if is_completion:
            choice["text"] = "ok"
        else:
            choice["delta" if stream else "message"] = {
                "role": "assistant",
                "content": "ok",
            }
        payload.update(
            object="text_completion" if is_completion else "chat.completion",
            created=1,
            choices=[choice],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )
    kwargs = {"method": "POST", "url": f"https://api.openai.com/v1/{endpoint}"}
    if stream:
        if is_responses:
            events = [
                {
                    "type": "response.output_text.delta",
                    "item_id": "message-1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "ok",
                },
                {"type": "response.completed", "response": payload},
            ]
        else:
            events = [payload]
        chunks = [f"data: {json.dumps(event)}\n\n".encode() for event in events]
        if not is_responses:
            chunks.append(b"data: [DONE]\n\n")
        kwargs.update(
            stream=IteratorStream(chunks),
            headers={"Content-Type": "text/event-stream"},
        )
    else:
        kwargs["json"] = payload
    httpx2_mock.add_response(**kwargs)


async def consume(response, async_):
    if async_:
        assert await response.text() == "ok"
        return await response.to_sync_response()
    assert response.text() == "ok"
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class", [Chat, AsyncChat, Responses, AsyncResponses, Completion]
)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reported_model", ["alias-2026-09-01", "alias", None, ""])
async def test_reported_model_is_logged(
    httpx2_mock, logs_db, model_class, stream, reported_model
):
    mock_response(httpx2_mock, model_class, stream, reported_model)
    model = model_class("alias")
    response = model.prompt("hello", key="test-key", stream=stream)
    response = await consume(
        response, issubclass(model_class, (AsyncChat, AsyncResponses))
    )
    expected = reported_model if reported_model and reported_model != "alias" else None
    assert response.resolved_model == expected
    response.log_to_db(logs_db)
    assert next(logs_db["turns"].rows)["resolved_model"] == expected
    requests = httpx2_mock.get_requests()
    assert len(requests) == 1
    assert json.loads(requests[0].content)["model"] == "alias"


@pytest.mark.asyncio
@pytest.mark.parametrize("model_class", [Responses, AsyncResponses])
@pytest.mark.parametrize("stream", [False, True])
async def test_chat_completions_override_records_model(
    httpx2_mock, model_class, stream
):
    mock_response(httpx2_mock, Chat, stream, "alias-2026-09-01")
    model = model_class("alias")
    response = model.prompt(
        "hello", key="test-key", stream=stream, chat_completions=True
    )
    response = await consume(response, model_class is AsyncResponses)
    assert response.resolved_model == "alias-2026-09-01"
    assert len(httpx2_mock.get_requests()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model_class", [Chat, AsyncChat, Responses, AsyncResponses])
@pytest.mark.parametrize("stream", [False, True])
async def test_custom_model_name_records_provider_id(httpx2_mock, model_class, stream):
    mock_response(httpx2_mock, model_class, stream, "provider-model")
    model = model_class("local-name", model_name="provider-model")
    response = model.prompt("hello", key="test-key", stream=stream)
    response = await consume(
        response, issubclass(model_class, (AsyncChat, AsyncResponses))
    )
    assert response.resolved_model == "provider-model"
    requests = httpx2_mock.get_requests()
    assert len(requests) == 1
    assert json.loads(requests[0].content)["model"] == "provider-model"
