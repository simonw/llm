"""Debug logging of raw HTTP traffic.

Kept out of llm.utils so CLI startup does not import httpx2.
"""

import json
import textwrap

import click
import httpx2


class _LogResponse(httpx2.Response):
    def iter_bytes(self, *args, **kwargs):
        for chunk in super().iter_bytes(*args, **kwargs):
            click.echo(chunk.decode(), err=True)
            yield chunk

    async def aiter_bytes(self, *args, **kwargs):
        async for chunk in super().aiter_bytes(*args, **kwargs):
            click.echo(chunk.decode(), err=True)
            yield chunk


class _LogTransport(httpx2.BaseTransport):
    def __init__(self, transport: httpx2.BaseTransport):
        self.transport = transport

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        response = self.transport.handle_request(request)
        return _LogResponse(
            status_code=response.status_code,
            headers=response.headers,
            stream=response.stream,
            extensions=response.extensions,
        )


class _AsyncLogTransport(httpx2.AsyncBaseTransport):
    def __init__(self, transport: httpx2.AsyncBaseTransport):
        self.transport = transport

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self.transport.handle_async_request(request)
        return _LogResponse(
            status_code=response.status_code,
            headers=response.headers,
            stream=response.stream,
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.transport.aclose()


def _no_accept_encoding(request: httpx2.Request):
    request.headers.pop("accept-encoding", None)


def _log_response(response: httpx2.Response):
    request = response.request
    click.echo(f"Request: {request.method} {request.url}", err=True)
    click.echo("  Headers:", err=True)
    for key, value in request.headers.items():
        if key.lower() == "authorization":
            value = "[...]"
        if key.lower() == "cookie":
            value = value.split("=")[0] + "=..."
        click.echo(f"    {key}: {value}", err=True)
    click.echo("  Body:", err=True)
    try:
        request_body = json.loads(request.content)
        click.echo(
            textwrap.indent(json.dumps(request_body, indent=2), "    "), err=True
        )
    except json.JSONDecodeError:
        click.echo(textwrap.indent(request.content.decode(), "    "), err=True)
    click.echo(f"Response: status_code={response.status_code}", err=True)
    click.echo("  Headers:", err=True)
    for key, value in response.headers.items():
        if key.lower() == "set-cookie":
            value = value.split("=")[0] + "=..."
        click.echo(f"    {key}: {value}", err=True)
    click.echo("  Body:", err=True)


async def _async_no_accept_encoding(request: httpx2.Request):
    _no_accept_encoding(request)


async def _async_log_response(response: httpx2.Response):
    _log_response(response)


def logging_client(*, async_=False) -> httpx2.Client | httpx2.AsyncClient:
    if async_:
        return httpx2.AsyncClient(
            transport=_AsyncLogTransport(httpx2.AsyncHTTPTransport()),
            event_hooks={
                "request": [_async_no_accept_encoding],
                "response": [_async_log_response],
            },
        )
    return httpx2.Client(
        transport=_LogTransport(httpx2.HTTPTransport()),
        event_hooks={"request": [_no_accept_encoding], "response": [_log_response]},
    )
