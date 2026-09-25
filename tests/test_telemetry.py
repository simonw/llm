import asyncio
import json

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind, StatusCode

import llm

_exporter = InMemorySpanExporter()


@pytest.fixture(scope="session")
def _provider():
    # The global tracer provider can only be set once per process
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture
def exporter(_provider):
    _exporter.clear()
    yield _exporter
    _exporter.clear()


def chat_spans(exporter):
    return [s for s in exporter.get_finished_spans() if s.name.startswith("chat ")]


@pytest.mark.parametrize("stream", (True, False))
def test_sync_prompt(exporter, mock_model, stream):
    mock_model.enqueue(["hello ", "world"])
    # Exact attribute equality below also proves no prompt text is recorded
    response = mock_model.prompt("top secret prompt", system="hidden", stream=stream)
    assert response.text() == "hello world"
    (span,) = chat_spans(exporter)
    assert span.name == "chat mock"
    assert span.kind == SpanKind.CLIENT
    assert span.status.status_code == StatusCode.UNSET
    attributes = dict(span.attributes)
    ttfc = attributes.pop("gen_ai.response.time_to_first_chunk", None)
    assert (ttfc is not None) == stream
    assert attributes == {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "unknown",
        "gen_ai.request.model": "mock",
        "gen_ai.request.stream": stream,
        "llm.response.id": response.id,
        "gen_ai.usage.input_tokens": 3,
        "gen_ai.usage.output_tokens": 2,
        "llm.response.outcome": "ok",
    }
    # A completed response replays without a new span
    exporter.clear()
    assert list(response) == ["hello ", "world"]
    assert chat_spans(exporter) == []


@pytest.mark.asyncio
async def test_async_prompt_and_conversation(exporter, async_mock_model):
    async_mock_model.enqueue(["hello ", "world"])
    conversation = async_mock_model.conversation()
    response = conversation.prompt("two words")
    assert await response.text() == "hello world"
    (span,) = chat_spans(exporter)
    assert span.name == "chat mock"
    assert span.kind == SpanKind.CLIENT
    assert span.attributes["gen_ai.conversation.id"] == conversation.id
    assert span.attributes["gen_ai.usage.input_tokens"] == 2
    assert span.attributes["gen_ai.usage.output_tokens"] == 2
    assert span.attributes["llm.response.outcome"] == "ok"
    assert span.attributes["llm.response.id"] == response.id


def test_chain_one_span_per_round_trip(exporter):
    def multiply(a: int, b: int) -> int:
        return a * b

    model = llm.get_model("echo")
    chain = model.chain(
        json.dumps(
            {"tool_calls": [{"name": "multiply", "arguments": {"a": 2, "b": 3}}]}
        ),
        tools=[multiply],
    )
    chain.text()
    spans = chat_spans(exporter)
    assert [s.name for s in spans] == ["chat echo", "chat echo"]
    assert {s.attributes["gen_ai.provider.name"] for s in spans} == {"echo"}


class FailingModel(llm.Model):
    model_id = "failing"
    can_stream = True

    def execute(self, prompt, stream, response, conversation):
        yield "partial"
        raise ValueError("secret error message")


class AsyncFailingModel(llm.AsyncModel):
    model_id = "failing"
    can_stream = True

    async def execute(self, prompt, stream, response, conversation):
        yield "partial"
        raise ValueError("secret error message")


@pytest.mark.asyncio
@pytest.mark.parametrize("is_async", (False, True))
async def test_model_error(exporter, is_async):
    with pytest.raises(ValueError):
        if is_async:
            await AsyncFailingModel().prompt("hi").text()
        else:
            FailingModel().prompt("hi").text()
    (span,) = chat_spans(exporter)
    assert span.attributes["llm.response.outcome"] == "error"
    assert span.attributes["error.type"] == "ValueError"
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is None
    assert "secret" not in repr(dict(span.attributes))


class SlowAsyncModel(llm.AsyncModel):
    model_id = "slow"
    can_stream = True

    async def execute(self, prompt, stream, response, conversation):
        yield "one"
        await asyncio.sleep(10)
        yield "two"


@pytest.mark.asyncio
async def test_task_cancelled_mid_stream(exporter):
    response = SlowAsyncModel().prompt("hi")
    started = asyncio.Event()

    async def consume():
        async for _ in response:
            started.set()

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (span,) = chat_spans(exporter)
    assert span.attributes["llm.response.outcome"] == "cancelled"
    assert span.attributes["error.type"] == "CancelledError"
    assert span.status.status_code == StatusCode.UNSET


def test_sync_abandoned_stream(exporter, mock_model):
    mock_model.enqueue(["a", "b", "c"])
    with trace.get_tracer("test").start_as_current_span("caller") as caller:
        for chunk in mock_model.prompt("hi"):
            break
        assert trace.get_current_span() is caller
    (span,) = chat_spans(exporter)
    assert span.attributes["llm.response.outcome"] == "abandoned"
    assert "error.type" not in span.attributes
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.asyncio
async def test_async_abandoned_stream_restores_current_span(exporter, async_mock_model):
    async_mock_model.enqueue(["a", "b", "c"])
    response = async_mock_model.prompt("hi")
    with trace.get_tracer("test").start_as_current_span("caller") as caller:
        async for chunk in response:
            break
        assert trace.get_current_span() is caller
    # The span stays open until the response is completed later
    assert chat_spans(exporter) == []
    assert await response.text() == "abc"
    (span,) = chat_spans(exporter)
    assert span.attributes["llm.response.outcome"] == "ok"


@pytest.mark.asyncio
async def test_async_closed_astream_events_is_abandoned(exporter):
    response = SlowAsyncModel().prompt("hi")
    events = response.astream_events()
    async for event in events:
        break
    await asyncio.sleep(0.1)
    await events.aclose()
    (span,) = chat_spans(exporter)
    assert span.attributes["llm.response.outcome"] == "abandoned"
    # Ends at the last chunk, not when it was closed
    assert span.end_time - span.start_time < 0.1 * 1e9


tracer = trace.get_tracer("test")


class NestingModel(llm.Model):
    model_id = "nesting"

    def execute(self, prompt, stream, response, conversation):
        with tracer.start_as_current_span("http"):
            pass
        yield "ok"


class AsyncNestingModel(llm.AsyncModel):
    model_id = "nesting"

    async def execute(self, prompt, stream, response, conversation):
        yield "o"
        with tracer.start_as_current_span("http"):
            await asyncio.sleep(0)
        yield "k"


@pytest.mark.asyncio
@pytest.mark.parametrize("is_async", (False, True))
async def test_parent_is_callers_span_and_provider_spans_nest(exporter, is_async):
    with tracer.start_as_current_span("caller") as caller:
        if is_async:
            await AsyncNestingModel().prompt("hi").text()
        else:
            NestingModel().prompt("hi").text()
    spans = {s.name: s for s in exporter.get_finished_spans()}
    chat = spans["chat nesting"]
    assert chat.parent.span_id == caller.get_span_context().span_id
    assert spans["http"].parent.span_id == chat.context.span_id
