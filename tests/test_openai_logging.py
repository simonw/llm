import asyncio

import httpx2
import pytest

from llm.default_plugins.openai_models import AsyncChat, Chat


@pytest.mark.parametrize("async_", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_debug_logging(monkeypatch, capsys, async_, stream):
    monkeypatch.setenv("LLM_OPENAI_SHOW_RESPONSES", "1")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(
            200,
            headers={"set-cookie": "session=response-secret"},
            content=b'{"result":"logged response"}',
        )

    transport = httpx2.MockTransport(respond)
    monkeypatch.setattr(httpx2, "HTTPTransport", lambda: transport)
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda: transport)
    model = AsyncChat("gpt-4o-mini") if async_ else Chat("gpt-4o-mini")
    client = model.get_client("key-secret", async_=async_)
    kwargs = {
        "json": {"prompt": "logged request"},
        "headers": {
            "cookie": "session=request-secret",
            "authorization": "Bearer key-secret",
        },
    }

    async def run_async():
        async with (
            client,
            client._client.stream(
                "POST", "https://example.com/test", **kwargs
            ) as response,
        ):
            if stream:
                return b"".join([chunk async for chunk in response.aiter_bytes()])
            return await response.aread()

    if async_:
        body = asyncio.run(run_async())
    else:
        with (
            client,
            client._client.stream(
                "POST", "https://example.com/test", **kwargs
            ) as response,
        ):
            body = b"".join(response.iter_bytes()) if stream else response.read()

    assert body == b'{"result":"logged response"}'
    assert "accept-encoding" not in requests[0].headers
    output = capsys.readouterr().err
    assert "Request: POST https://example.com/test" in output
    assert "Response: status_code=200" in output
    assert "logged request" in output
    assert "logged response" in output
    assert "session=..." in output
    assert "request-secret" not in output
    assert "response-secret" not in output
    assert "key-secret" not in output
