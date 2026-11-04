"""OpenTelemetry spans for llm (``opentelemetry-api`` only; a no-op without
an SDK): a ``chat {model_id}`` CLIENT span per ``execute()`` call and an
``execute_tool {name}`` span per tool call. Never records prompt, response,
tool argument or error message text. See docs/telemetry.md for lifetimes."""

import asyncio
import importlib.metadata
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import context, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

try:
    _version = importlib.metadata.version("llm")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    _version = "unknown"

tracer = trace.get_tracer("llm", _version)

GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_REQUEST_STREAM = "gen_ai.request.stream"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_RESPONSE_TIME_TO_FIRST_CHUNK = "gen_ai.response.time_to_first_chunk"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
ERROR_TYPE = "error.type"
LLM_RESPONSE_ID = "llm.response.id"
# ok | error | cancelled | abandoned
LLM_RESPONSE_OUTCOME = "llm.response.outcome"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
# ok | error | cancelled | paused
LLM_TOOL_OUTCOME = "llm.tool.outcome"

# Cancellation is a designed way for work to end: outcome cancelled, status UNSET
_CANCELLED = (asyncio.CancelledError, KeyboardInterrupt)

# Semconv well-known names for plugins whose package name differs.
_PROVIDER_ALIASES = {
    "gemini": "gcp.gemini",
    "vertex": "gcp.vertex_ai",
    "mistral": "mistral_ai",
    "grok": "x_ai",
    "bedrock": "aws.bedrock",
    "watsonx": "ibm.watsonx.ai",
}


def provider_name_for(model: Any) -> str:
    "From the model's module (never its user-configurable id): llm_foo -> foo"
    module = type(model).__module__ or ""
    if module.startswith("llm.default_plugins.openai"):
        return "openai"
    top = module.split(".", 1)[0]
    if not top.startswith("llm_") or len(top) == 4:
        return "unknown"
    name = top[4:]
    return _PROVIDER_ALIASES.get(name, name)


class ChatSpan:
    "One ``chat {model_id}`` span, started unattached."

    def __init__(self, response: Any):
        self.response = response
        self.stream = bool(response.stream)
        self.provider = provider_name_for(response.model)
        self.model_id = getattr(response.model, "model_id", None) or "unknown"
        self.started = time.perf_counter()
        self.first_chunk: float | None = None
        self.last_step: int | None = None
        self.span = tracer.start_span(f"chat {self.model_id}", kind=SpanKind.CLIENT)
        self.context = trace.set_span_in_context(self.span)
        self.span.set_attributes(
            {
                GEN_AI_OPERATION_NAME: "chat",
                GEN_AI_PROVIDER_NAME: self.provider,
                GEN_AI_REQUEST_MODEL: self.model_id,
                GEN_AI_REQUEST_STREAM: self.stream,
                LLM_RESPONSE_ID: str(response.id),
            }
        )
        conversation_id = getattr(response.conversation, "id", None)
        if conversation_id:
            self.span.set_attribute(GEN_AI_CONVERSATION_ID, str(conversation_id))

    @contextmanager
    def current(self):
        "Make the span current for one step of the plugin generator."
        token = context.attach(self.context)
        try:
            yield
        finally:
            context.detach(token)

    def chunk(self) -> None:
        self.last_step = time.time_ns()
        if self.first_chunk is None:
            self.first_chunk = time.perf_counter() - self.started

    def fail(self, exception: BaseException) -> None:
        "End as ``cancelled`` (status UNSET) or ``error`` (status ERROR)."
        outcome = "cancelled" if isinstance(exception, _CANCELLED) else "error"
        self.end(outcome, error_type=type(exception).__qualname__)

    def end(self, outcome: str = "ok", error_type: str | None = None) -> None:
        span = self.span
        span.set_attribute(LLM_RESPONSE_OUTCOME, outcome)
        if error_type is not None:
            span.set_attribute(ERROR_TYPE, error_type)
        if outcome == "error":
            span.set_status(Status(StatusCode.ERROR))
        if self.stream and self.first_chunk is not None:
            span.set_attribute(GEN_AI_RESPONSE_TIME_TO_FIRST_CHUNK, self.first_chunk)
        for attribute, value in (
            (GEN_AI_USAGE_INPUT_TOKENS, self.response.input_tokens),
            (GEN_AI_USAGE_OUTPUT_TOKENS, self.response.output_tokens),
        ):
            if value is not None:
                span.set_attribute(attribute, value)
        # An abandoned span ends at its last chunk, not whenever the
        # generator happened to be closed or garbage collected.
        span.end(end_time=self.last_step if outcome == "abandoned" else None)


def traced(response: Any, chunks: Any) -> Iterator[Any]:
    "Yield from a sync ``execute()`` result inside a chat span."
    iterator = iter(chunks)
    chat = ChatSpan(response)
    try:
        while True:
            try:
                with chat.current():
                    chunk = next(iterator)
            except StopIteration:
                break
            chat.chunk()
            yield chunk
    except GeneratorExit:
        try:
            with chat.current():
                getattr(iterator, "close", lambda: None)()
        finally:
            chat.end("abandoned")
        raise
    except BaseException as exception:
        chat.fail(exception)
        raise
    chat.end()


async def atraced(response: Any, chunks: Any) -> AsyncIterator[Any]:
    "Async counterpart of ``traced()``."
    chat = ChatSpan(response)
    try:
        while True:
            try:
                with chat.current():
                    chunk = await chunks.__anext__()
            except StopAsyncIteration:
                break
            chat.chunk()
            yield chunk
    except GeneratorExit:
        try:
            with chat.current():
                if hasattr(chunks, "aclose"):
                    await chunks.aclose()
        finally:
            chat.end("abandoned")
        raise
    except BaseException as exception:
        chat.fail(exception)
        raise
    chat.end()


@contextmanager
def tool_span(tool_call: Any) -> Iterator[None]:
    """``execute_tool {name}`` around one tool implementation call. A
    ``PauseChain`` is outcome ``paused`` with status UNSET, not an error."""
    from .models import PauseChain

    with tracer.start_as_current_span(
        f"execute_tool {tool_call.name}",
        kind=SpanKind.INTERNAL,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attributes(
            {GEN_AI_OPERATION_NAME: "execute_tool", GEN_AI_TOOL_NAME: tool_call.name}
        )
        if tool_call.tool_call_id:
            span.set_attribute(GEN_AI_TOOL_CALL_ID, tool_call.tool_call_id)
        outcome = "ok"
        try:
            yield
        except PauseChain:
            outcome = "paused"
            raise
        except BaseException as exception:
            outcome = "cancelled" if isinstance(exception, _CANCELLED) else "error"
            span.set_attribute(ERROR_TYPE, type(exception).__qualname__)
            if outcome == "error":
                span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute(LLM_TOOL_OUTCOME, outcome)
