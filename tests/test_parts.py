"""Tests for Part types, StreamEvent, and Response integration."""

import json
import os
import pytest
from click.testing import CliRunner
from pytest_httpx import IteratorStream
import llm
from llm.cli import cli

API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


class TestExports:
    def test_part_types_exported_from_llm(self):
        import llm

        assert llm.Part is not None
        assert llm.TextPart is not None
        assert llm.ReasoningPart is not None
        assert llm.ToolCallPart is not None
        assert llm.ToolResultPart is not None
        assert llm.AttachmentPart is not None
        assert llm.StreamEvent is not None


# Phase 1: Part types and serialization


class TestPartTypes:
    def test_text_part_creation(self):
        from llm.parts import TextPart

        part = TextPart(text="Hello world")
        assert part.text == "Hello world"

    def test_reasoning_part_creation(self):
        from llm.parts import ReasoningPart

        part = ReasoningPart(text="Let me think...")
        assert part.text == "Let me think..."
        assert part.redacted is False
        assert part.token_count is None

    def test_reasoning_part_redacted(self):
        from llm.parts import ReasoningPart

        part = ReasoningPart(text="", redacted=True, token_count=150)
        assert part.redacted is True
        assert part.token_count == 150

    def test_tool_call_part_creation(self):
        from llm.parts import ToolCallPart

        part = ToolCallPart(
            name="search",
            arguments={"query": "weather"},
            tool_call_id="call_123",
        )
        assert part.name == "search"
        assert part.arguments == {"query": "weather"}
        assert part.tool_call_id == "call_123"
        assert part.server_executed is False

    def test_tool_result_part_creation(self):
        from llm.parts import ToolResultPart

        part = ToolResultPart(
            name="search",
            output="Sunny, 72F",
            tool_call_id="call_123",
        )
        assert part.name == "search"
        assert part.output == "Sunny, 72F"
        assert part.tool_call_id == "call_123"
        assert part.server_executed is False
        assert part.attachments == []
        assert part.exception is None

    def test_attachment_part_creation(self):
        from llm.parts import AttachmentPart
        from llm import Attachment

        att = Attachment(type="image/png", content=b"fake png")
        part = AttachmentPart(attachment=att)
        assert part.attachment is att


class TestPartSerialization:
    def test_text_part_roundtrip(self):
        from llm.parts import TextPart, Part

        part = TextPart(text="Hello")
        d = part.to_dict()
        assert d == {"type": "text", "text": "Hello"}
        restored = Part.from_dict(d)
        assert isinstance(restored, TextPart)
        assert restored.text == "Hello"

    def test_reasoning_part_roundtrip(self):
        from llm.parts import ReasoningPart, Part

        part = ReasoningPart(text="thinking...")
        d = part.to_dict()
        assert d == {"type": "reasoning", "text": "thinking..."}
        restored = Part.from_dict(d)
        assert isinstance(restored, ReasoningPart)
        assert restored.text == "thinking..."
        assert restored.redacted is False

    def test_reasoning_part_redacted_roundtrip(self):
        from llm.parts import ReasoningPart, Part

        part = ReasoningPart(text="", redacted=True, token_count=42)
        d = part.to_dict()
        assert d["redacted"] is True
        assert d["token_count"] == 42
        restored = Part.from_dict(d)
        assert isinstance(restored, ReasoningPart)
        assert restored.redacted is True
        assert restored.token_count == 42

    def test_tool_call_part_roundtrip(self):
        from llm.parts import ToolCallPart, Part

        part = ToolCallPart(
            name="search",
            arguments={"q": "test"},
            tool_call_id="call_1",
            server_executed=True,
        )
        d = part.to_dict()
        assert d["type"] == "tool_call"
        assert d["name"] == "search"
        assert d["arguments"] == {"q": "test"}
        assert d["tool_call_id"] == "call_1"
        assert d["server_executed"] is True
        restored = Part.from_dict(d)
        assert isinstance(restored, ToolCallPart)
        assert restored.name == "search"
        assert restored.server_executed is True

    def test_tool_result_part_roundtrip(self):
        from llm.parts import ToolResultPart, Part

        part = ToolResultPart(
            name="search",
            output="result",
            tool_call_id="call_1",
            exception="SomeError",
        )
        d = part.to_dict()
        assert d["type"] == "tool_result"
        assert d["exception"] == "SomeError"
        restored = Part.from_dict(d)
        assert isinstance(restored, ToolResultPart)
        assert restored.exception == "SomeError"

    def test_from_dict_unknown_type_raises(self):
        from llm.parts import Part

        with pytest.raises(ValueError, match="Unknown part type"):
            Part.from_dict({"type": "unknown_thing"})


class TestStreamEvent:
    def test_stream_event_creation(self):
        from llm.parts import StreamEvent

        event = StreamEvent(type="text", chunk="hello", part_index=0)
        assert event.type == "text"
        assert event.chunk == "hello"
        assert event.part_index == 0
        assert event.tool_call_id is None

    def test_stream_event_with_tool_call_id(self):
        from llm.parts import StreamEvent

        event = StreamEvent(
            type="tool_call_args",
            chunk='{"q": "test"}',
            part_index=1,
            tool_call_id="call_123",
        )
        assert event.tool_call_id == "call_123"


# Phase 1: stream_events() and parts property on Response


class TestResponseStreamEvents:
    """Test that Response.stream_events() wraps plain str chunks as text StreamEvents."""

    def test_stream_events_from_plain_str_chunks(self, mock_model):
        mock_model.enqueue(["Hello", " world"])
        response = mock_model.prompt("hi")
        events = list(response.stream_events())
        assert len(events) == 2
        assert all(e.type == "text" for e in events)
        assert events[0].chunk == "Hello"
        assert events[1].chunk == " world"
        assert all(e.part_index == 0 for e in events)

    def test_stream_events_after_text(self, mock_model):
        """stream_events() works even after text() has been called (response is done)."""
        mock_model.enqueue(["Hello", " world"])
        response = mock_model.prompt("hi")
        assert response.text() == "Hello world"
        events = list(response.stream_events())
        # After completion, stream_events replays from parts
        assert len(events) == 1
        assert events[0].type == "text"
        assert events[0].chunk == "Hello world"

    def test_parts_from_plain_str_response(self, mock_model):
        """[p for m in response.messages for p in m.parts] returns a list of Part objects after completion."""
        from llm.parts import TextPart

        mock_model.enqueue(["Hello", " world"])
        response = mock_model.prompt("hi")
        response.text()  # Force completion
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello world"

    def test_parts_not_done_forces(self, mock_model):
        """Accessing parts forces the response to complete."""
        from llm.parts import TextPart

        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("hi")
        # Don't call text() or iterate - just access parts directly
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello"


class TestResponsePartsIterAndText:
    """Verify that iterating and text() still work as before (backward compat)."""

    def test_iter_yields_str(self, mock_model):
        mock_model.enqueue(["a", "b", "c"])
        response = mock_model.prompt("hi")
        chunks = list(response)
        assert chunks == ["a", "b", "c"]
        assert all(isinstance(c, str) for c in chunks)

    def test_text_returns_joined(self, mock_model):
        mock_model.enqueue(["Hello", " ", "world"])
        response = mock_model.prompt("hi")
        assert response.text() == "Hello world"


@pytest.mark.asyncio
class TestAsyncResponseStreamEvents:
    async def test_async_stream_events(self, async_mock_model):
        async_mock_model.enqueue(["Hello", " world"])
        response = async_mock_model.prompt("hi")
        events = []
        async for event in response.astream_events():
            events.append(event)
        assert len(events) == 2
        assert all(e.type == "text" for e in events)
        assert events[0].chunk == "Hello"
        assert events[1].chunk == " world"

    async def test_async_parts(self, async_mock_model):
        from llm.parts import TextPart

        async_mock_model.enqueue(["Hello", " world"])
        response = async_mock_model.prompt("hi")
        await response.text()
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello world"


# Phase 2: Response handles StreamEvent from plugins


class StreamEventModel(llm.Model):
    """A mock model that yields StreamEvents from execute()."""

    model_id = "stream-event-mock"

    def __init__(self):
        self._queue = []

    def enqueue(self, items):
        """Enqueue items to yield. Can be str or StreamEvent."""
        self._queue.append(items)

    def execute(self, prompt, stream, response, conversation):
        while self._queue:
            items = self._queue.pop(0)
            for item in items:
                yield item


class AsyncStreamEventModel(llm.AsyncModel):
    """Async mock model that yields StreamEvents from execute()."""

    model_id = "stream-event-mock"

    def __init__(self):
        self._queue = []

    def enqueue(self, items):
        self._queue.append(items)

    async def execute(self, prompt, stream, response, conversation):
        while self._queue:
            items = self._queue.pop(0)
            for item in items:
                yield item


class TestPhase2StreamEventHandling:
    """Response.__iter__ handles str | StreamEvent from execute()."""

    def test_plain_str_backward_compat(self):
        """Plain str chunks still work as before."""
        model = StreamEventModel()
        model.enqueue(["Hello", " world"])
        response = model.prompt("hi")
        assert list(response) == ["Hello", " world"]
        assert response.text() == "Hello world"

    def test_stream_event_text_yields_str(self):
        """StreamEvent(type='text') yields the chunk as str to iterators."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="text", chunk="Hello", part_index=0),
                StreamEvent(type="text", chunk=" world", part_index=0),
            ]
        )
        response = model.prompt("hi")
        chunks = list(response)
        assert chunks == ["Hello", " world"]
        assert response.text() == "Hello world"

    def test_mixed_str_and_stream_events(self):
        """Mix of str and StreamEvent in same execute() works."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue(
            [
                "plain ",
                StreamEvent(type="text", chunk="event", part_index=0),
            ]
        )
        response = model.prompt("hi")
        chunks = list(response)
        assert chunks == ["plain ", "event"]

    def test_reasoning_events_not_in_iter(self):
        """Reasoning StreamEvents are silently filtered from __iter__ but appear in stream_events()."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="Let me think...", part_index=0),
                StreamEvent(type="text", chunk="The answer is 42", part_index=1),
            ]
        )
        response = model.prompt("question")
        # Regular iteration only yields text
        chunks = list(response)
        assert chunks == ["The answer is 42"]

    def test_stream_events_yields_all_types(self):
        """stream_events() yields ALL event types including reasoning."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="thinking...", part_index=0),
                StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        response = model.prompt("question")
        events = list(response.stream_events())
        assert len(events) == 2
        assert events[0].type == "reasoning"
        assert events[0].chunk == "thinking..."
        assert events[1].type == "text"
        assert events[1].chunk == "answer"

    def test_parts_assembled_from_stream_events(self):
        """[p for m in response.messages for p in m.parts] assembles Part objects from StreamEvents."""
        from llm.parts import StreamEvent, TextPart, ReasoningPart

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="Let me ", part_index=0),
                StreamEvent(type="reasoning", chunk="think...", part_index=0),
                StreamEvent(type="text", chunk="The ", part_index=1),
                StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        response = model.prompt("question")
        response.text()  # Force completion
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 2
        assert isinstance(parts[0], ReasoningPart)
        assert parts[0].text == "Let me think..."
        assert isinstance(parts[1], TextPart)
        assert parts[1].text == "The answer"

    def test_tool_call_parts_assembled(self):
        """Tool call StreamEvents are assembled into ToolCallPart."""
        from llm.parts import StreamEvent, TextPart, ToolCallPart

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="text", chunk="Let me search", part_index=0),
                StreamEvent(
                    type="tool_call_name",
                    chunk="search",
                    part_index=1,
                    tool_call_id="call_1",
                ),
                StreamEvent(
                    type="tool_call_args",
                    chunk='{"query": ',
                    part_index=1,
                    tool_call_id="call_1",
                ),
                StreamEvent(
                    type="tool_call_args",
                    chunk='"weather"}',
                    part_index=1,
                    tool_call_id="call_1",
                ),
            ]
        )
        response = model.prompt("what's the weather?")
        response.text()
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 2
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Let me search"
        assert isinstance(parts[1], ToolCallPart)
        assert parts[1].name == "search"
        assert parts[1].arguments == {"query": "weather"}
        assert parts[1].tool_call_id == "call_1"

    def test_tool_result_part_assembled(self):
        """Server-side tool result StreamEvents assembled into ToolResultPart."""
        from llm.parts import StreamEvent, ToolCallPart, ToolResultPart

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(
                    type="tool_call_name",
                    chunk="code_exec",
                    part_index=0,
                    tool_call_id="call_1",
                    server_executed=True,
                ),
                StreamEvent(
                    type="tool_call_args",
                    chunk='{"code": "1+1"}',
                    part_index=0,
                    tool_call_id="call_1",
                    server_executed=True,
                ),
                StreamEvent(
                    type="tool_result",
                    chunk="2",
                    part_index=1,
                    tool_call_id="call_1",
                    server_executed=True,
                ),
                StreamEvent(type="text", chunk="The answer is 2", part_index=2),
            ]
        )
        response = model.prompt("compute")
        response.text()
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 3
        assert isinstance(parts[0], ToolCallPart)
        assert parts[0].server_executed is True
        assert isinstance(parts[1], ToolResultPart)
        assert parts[1].output == "2"
        assert parts[1].server_executed is True
        assert parts[1].tool_call_id == "call_1"

    def test_tool_call_events_not_in_iter(self):
        """Tool call StreamEvents are filtered from __iter__."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="text", chunk="searching...", part_index=0),
                StreamEvent(
                    type="tool_call_name",
                    chunk="search",
                    part_index=1,
                    tool_call_id="call_1",
                ),
                StreamEvent(
                    type="tool_call_args",
                    chunk='{"q": "test"}',
                    part_index=1,
                    tool_call_id="call_1",
                ),
            ]
        )
        response = model.prompt("hi")
        chunks = list(response)
        assert chunks == ["searching..."]


@pytest.mark.asyncio
class TestPhase2AsyncStreamEventHandling:
    async def test_async_stream_event_text(self):
        """Async: StreamEvent(type='text') yields str chunks."""
        from llm.parts import StreamEvent

        model = AsyncStreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="text", chunk="Hello", part_index=0),
                StreamEvent(type="text", chunk=" world", part_index=0),
            ]
        )
        response = model.prompt("hi")
        chunks = []
        async for chunk in response:
            chunks.append(chunk)
        assert chunks == ["Hello", " world"]

    async def test_async_reasoning_filtered_from_iter(self):
        """Async: reasoning events filtered from __aiter__."""
        from llm.parts import StreamEvent

        model = AsyncStreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="thinking", part_index=0),
                StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        response = model.prompt("hi")
        chunks = []
        async for chunk in response:
            chunks.append(chunk)
        assert chunks == ["answer"]

    async def test_async_astream_events_all_types(self):
        """Async: astream_events() yields all event types."""
        from llm.parts import StreamEvent

        model = AsyncStreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="thinking", part_index=0),
                StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        response = model.prompt("hi")
        events = []
        async for event in response.astream_events():
            events.append(event)
        assert len(events) == 2
        assert events[0].type == "reasoning"
        assert events[1].type == "text"

    async def test_async_parts_from_stream_events(self):
        """Async: parts assembled from StreamEvents."""
        from llm.parts import StreamEvent, TextPart, ReasoningPart

        model = AsyncStreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="hmm", part_index=0),
                StreamEvent(type="text", chunk="yes", part_index=1),
            ]
        )
        response = model.prompt("hi")
        await response.text()
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 2
        assert isinstance(parts[0], ReasoningPart)
        assert parts[0].text == "hmm"
        assert isinstance(parts[1], TextPart)
        assert parts[1].text == "yes"


# Phase 3: OpenAI plugin StreamEvent integration


def _openai_sse_chunks(deltas, usage=None):
    """Build SSE byte chunks from a list of delta dicts."""
    for i, (delta, finish_reason) in enumerate(deltas):
        chunk = {
            "id": "chat-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-5.4-mini",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        if usage and i == len(deltas) - 1:
            chunk["usage"] = usage
        yield ("data: " + json.dumps(chunk) + "\n\n").encode("utf-8")
    # Final usage-only chunk if usage provided
    if usage:
        yield (
            "data: "
            + json.dumps(
                {
                    "id": "chat-test",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "gpt-5.4-mini",
                    "choices": [],
                    "usage": usage,
                }
            )
            + "\n\n"
        ).encode("utf-8")
    yield b"data: [DONE]\n\n"


class TestOpenAIPluginStreamEvents:
    """Test that the OpenAI plugin yields StreamEvent objects."""

    def test_openai_text_stream_events(self, httpx_mock):
        """OpenAI streaming text yields StreamEvents via stream_events()."""
        from llm.parts import TextPart

        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks(
                    [
                        ({"role": "assistant", "content": ""}, None),
                        ({"content": "Hello"}, None),
                        ({"content": " world"}, None),
                        ({}, "stop"),
                    ]
                )
            ),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-5.4-mini")
        response = model.prompt("hi", key=API_KEY)
        events = list(response.stream_events())
        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) >= 2
        assert "Hello" in [e.chunk for e in text_events]
        assert " world" in [e.chunk for e in text_events]

        # Parts should have a single TextPart
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello world"

    def test_openai_iter_still_yields_str(self, httpx_mock):
        """Backward compat: iterating Response still yields str."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks(
                    [
                        ({"role": "assistant", "content": ""}, None),
                        ({"content": "Hi"}, None),
                        ({}, "stop"),
                    ]
                )
            ),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-5.4-mini")
        response = model.prompt("hi", key=API_KEY)
        chunks = list(response)
        assert all(isinstance(c, str) for c in chunks)
        assert "Hi" in chunks

    def test_openai_tool_call_stream_events(self, httpx_mock):
        """OpenAI streaming tool calls yield tool_call StreamEvents."""
        from llm.parts import ToolCallPart

        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks(
                    [
                        (
                            {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_abc",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": "",
                                        },
                                        "type": "function",
                                    }
                                ],
                            },
                            None,
                        ),
                        (
                            {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '{"city"'},
                                    }
                                ]
                            },
                            None,
                        ),
                        (
                            {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": ': "Paris"}'},
                                    }
                                ]
                            },
                            None,
                        ),
                        ({}, "stop"),
                    ]
                )
            ),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-5.4-mini")
        response = model.prompt("weather in Paris?", key=API_KEY)

        events = list(response.stream_events())
        name_events = [e for e in events if e.type == "tool_call_name"]
        args_events = [e for e in events if e.type == "tool_call_args"]
        assert len(name_events) == 1
        assert name_events[0].chunk == "get_weather"
        assert name_events[0].tool_call_id == "call_abc"
        assert len(args_events) >= 1

        # Parts should include a ToolCallPart
        parts = [p for m in response.messages for p in m.parts]
        tool_parts = [p for p in parts if isinstance(p, ToolCallPart)]
        assert len(tool_parts) == 1
        assert tool_parts[0].name == "get_weather"
        assert tool_parts[0].arguments == {"city": "Paris"}
        assert tool_parts[0].tool_call_id == "call_abc"

    def test_openai_reasoning_tokens_in_parts(self, httpx_mock):
        """When usage has reasoning_tokens > 0, parts include a redacted ReasoningPart."""
        from llm.parts import ReasoningPart, TextPart

        usage = {
            "prompt_tokens": 20,
            "completion_tokens": 50,
            "total_tokens": 70,
            "completion_tokens_details": {
                "reasoning_tokens": 16,
                "accepted_prediction_tokens": 0,
                "audio_tokens": 0,
                "rejected_prediction_tokens": 0,
            },
            "prompt_tokens_details": {
                "audio_tokens": 0,
                "cached_tokens": 0,
            },
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks(
                    [
                        ({"role": "assistant", "content": ""}, None),
                        ({"content": "Answer"}, None),
                        ({}, "stop"),
                    ],
                    usage=usage,
                )
            ),
            headers={"Content-Type": "text/event-stream"},
        )
        model = llm.get_model("gpt-5.4-mini")
        response = model.prompt("think hard", key=API_KEY)
        response.text()

        parts = [p for m in response.messages for p in m.parts]
        # Should have ReasoningPart (redacted) + TextPart
        reasoning_parts = [p for p in parts if isinstance(p, ReasoningPart)]
        text_parts = [p for p in parts if isinstance(p, TextPart)]
        assert len(reasoning_parts) == 1
        assert reasoning_parts[0].redacted is True
        assert reasoning_parts[0].token_count == 16
        assert len(text_parts) == 1
        assert text_parts[0].text == "Answer"

    def test_openai_non_streaming_parts(self, httpx_mock):
        """Non-streaming OpenAI response produces correct parts."""
        from llm.parts import TextPart

        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "model": "gpt-5.4-mini",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello!",
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            },
            headers={"Content-Type": "application/json"},
        )
        model = llm.get_model("gpt-5.4-mini")
        response = model.prompt("hi", key=API_KEY, stream=False)
        assert response.text() == "Hello!"
        parts = [p for m in response.messages for p in m.parts]
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello!"


# Phase 4: parts=[] prompt parameter


# TestPartsParameter removed: parts=[] is gone. See TestMessagesParameter and
# TestPromptMessagesSynthesis for messages= equivalents.


# Phase 5: Database migration for parts


class TestDatabaseParts:
    """Test that messages and parts are stored and loaded from the database."""

    def test_messages_and_message_parts_tables_created(self, logs_db):
        from llm.migrations import migrate

        migrate(logs_db)
        assert "messages" in logs_db.table_names()
        assert "message_parts" in logs_db.table_names()

    def test_log_to_db_writes_output_parts(self, mock_model, logs_db):
        from llm.migrations import migrate
        from llm.parts import StreamEvent

        migrate(logs_db)

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="thinking...", part_index=0),
                StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        response = model.prompt("question")
        response.text()
        response.log_to_db(logs_db)

        # One output message with two parts
        output_msgs = [
            m for m in logs_db["messages"].rows if m["direction"] == "output"
        ]
        assert len(output_msgs) == 1
        assert output_msgs[0]["role"] == "assistant"
        parts = [
            p
            for p in logs_db["message_parts"].rows
            if p["message_id"] == output_msgs[0]["id"]
        ]
        assert [p["part_type"] for p in parts] == ["reasoning", "text"]
        assert parts[0]["content"] == "thinking..."
        assert parts[1]["content"] == "answer"

    def test_log_to_db_writes_input_messages(self, mock_model, logs_db):
        from llm.migrations import migrate

        migrate(logs_db)

        mock_model.enqueue(["Hi"])
        response = mock_model.prompt("Hello", system="Be helpful")
        response.text()
        response.log_to_db(logs_db)

        input_msgs = [m for m in logs_db["messages"].rows if m["direction"] == "input"]
        assert [m["role"] for m in input_msgs] == ["system", "user"]

    def test_from_row_loads_parts(self, mock_model, logs_db):
        """from_row() loads parts from the parts table."""
        from llm.migrations import migrate
        from llm.parts import TextPart

        migrate(logs_db)

        mock_model.enqueue(["Hello world"])
        response = mock_model.prompt("Hi")
        response.text()
        response.log_to_db(logs_db)

        # Load from DB
        row = list(logs_db["responses"].rows)[0]
        loaded = llm.Response.from_row(logs_db, row)
        all_parts = [p for m in loaded.messages for p in m.parts]
        assert all_parts
        text_parts = [p for p in all_parts if isinstance(p, TextPart)]
        assert len(text_parts) >= 1
        assert text_parts[0].text == "Hello world"


# ChainResponse stream_events


class TestChainResponseStreamEvents:
    def test_chain_response_stream_events(self):
        """ChainResponse.stream_events() yields events from all responses."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        # First response: tool call
        model.enqueue(
            [
                StreamEvent(type="text", chunk="Let me check", part_index=0),
                StreamEvent(
                    type="tool_call_name",
                    chunk="lookup",
                    part_index=1,
                    tool_call_id="call_1",
                ),
                StreamEvent(
                    type="tool_call_args",
                    chunk="{}",
                    part_index=1,
                    tool_call_id="call_1",
                ),
            ]
        )
        response = model.prompt("test")
        # stream_events on a regular Response should work
        events = list(response.stream_events())
        assert len(events) == 3
        assert events[0].type == "text"
        assert events[1].type == "tool_call_name"

    def test_chain_stream_events_plain_str(self, mock_model):
        """ChainResponse.stream_events() works when plugin yields plain str."""
        mock_model.enqueue(["Hello ", "world"])
        response = mock_model.prompt("hi")
        events = list(response.stream_events())
        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) == 2
        assert text_events[0].chunk == "Hello "


# CLI reasoning display


class TestCLIReasoningDisplay:
    """Test that reasoning events are displayed on stderr."""

    def test_reasoning_shown_on_stderr(self, mock_model):
        """Reasoning text appears on stderr when streaming."""
        from llm.parts import StreamEvent

        # We need a model that emits reasoning StreamEvents.
        # The mock_model yields plain strings, so we need StreamEventModel.
        # But StreamEventModel isn't registered as a plugin.
        # Instead, test via the Python API pattern that the CLI uses.
        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(type="reasoning", chunk="thinking hard", part_index=0),
                StreamEvent(type="text", chunk="the answer", part_index=1),
            ]
        )
        response = model.prompt("question")
        # Collect text (stdout) and reasoning (stderr) events
        stdout_chunks = []
        stderr_chunks = []
        for event in response.stream_events():
            if event.type == "text":
                stdout_chunks.append(event.chunk)
            elif event.type == "reasoning":
                stderr_chunks.append(event.chunk)
        assert stdout_chunks == ["the answer"]
        assert stderr_chunks == ["thinking hard"]

    def test_reasoning_to_text_newline(self):
        """A newline is emitted on stderr when switching from reasoning to text."""
        from llm.parts import StreamEvent
        from llm.cli import display_stream_events
        import io

        events = [
            StreamEvent(type="reasoning", chunk="thinking", part_index=0),
            StreamEvent(type="reasoning", chunk=" more", part_index=0),
            StreamEvent(type="text", chunk="answer", part_index=1),
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        display_stream_events(events, stdout=stdout, stderr=stderr, show_reasoning=True)
        assert stdout.getvalue() == "answer"
        stderr_val = stderr.getvalue()
        assert "thinking" in stderr_val
        assert " more" in stderr_val
        assert stderr_val.endswith("\n"), "Should end with newline at transition"

    def test_reasoning_to_text_no_newline_when_suppressed(self):
        """No reasoning or newline when show_reasoning=False."""
        from llm.parts import StreamEvent
        from llm.cli import display_stream_events
        import io

        events = [
            StreamEvent(type="reasoning", chunk="thinking", part_index=0),
            StreamEvent(type="text", chunk="answer", part_index=1),
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        display_stream_events(
            events, stdout=stdout, stderr=stderr, show_reasoning=False
        )
        assert stdout.getvalue() == "answer"
        assert stderr.getvalue() == ""

    def test_multiple_reasoning_text_transitions(self):
        """Newlines on each reasoning-to-text transition."""
        from llm.parts import StreamEvent
        from llm.cli import display_stream_events
        import io

        events = [
            StreamEvent(type="reasoning", chunk="think1", part_index=0),
            StreamEvent(type="text", chunk="text1", part_index=1),
            StreamEvent(type="reasoning", chunk="think2", part_index=2),
            StreamEvent(type="text", chunk="text2", part_index=3),
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        display_stream_events(events, stdout=stdout, stderr=stderr, show_reasoning=True)
        assert stdout.getvalue() == "text1text2"
        stderr_val = stderr.getvalue()
        # Two reasoning-to-text transitions = two newlines
        assert stderr_val.count("\n") == 2
        assert "think1" in stderr_val
        assert "think2" in stderr_val

    def test_cli_no_reasoning_flag_exists(self):
        """--no-reasoning / -R flag is accepted by the prompt command."""
        runner = CliRunner()
        # Just check the flag is accepted (will fail because no model, but
        # shouldn't fail because of the flag itself)
        result = runner.invoke(cli, ["prompt", "--no-reasoning", "--help"])
        assert result.exit_code == 0
        assert "--no-reasoning" in result.output

    def test_cli_short_R_flag_exists(self):
        """Short -R flag is accepted by the prompt command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["prompt", "-R", "--help"])
        assert result.exit_code == 0


# Phase 7: OpenAI build_messages supports parts=[]


class TestBuildMessagesWithMessages:
    """Test that OpenAI build_messages correctly handles messages=[] parameter."""

    def test_build_messages_uses_messages(self, mocked_openai_chat, user_path):
        from llm import user, assistant, system as system_helper

        model = llm.get_model("gpt-4o-mini")
        model.key = "x"
        response = model.prompt(
            messages=[
                system_helper("You are a geography expert."),
                user("What is the capital of France?"),
                assistant("The capital of France is Paris."),
                user("What about Germany?"),
            ]
        )
        response.text()
        last_request = mocked_openai_chat.get_requests()[-1]
        messages = json.loads(last_request.content)["messages"]
        assert messages == [
            {"role": "system", "content": "You are a geography expert."},
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
            {"role": "user", "content": "What about Germany?"},
        ]


class TestPhaseBFixes:
    """Round-trip + stream assembler + tool parts in OpenAI build_messages."""

    def test_attachment_part_round_trips_with_content(self):
        from llm.parts import AttachmentPart, Part

        att = llm.Attachment(type="image/png", content=b"hello-bytes")
        d = AttachmentPart(attachment=att).to_dict()
        assert d["type"] == "attachment"
        restored = Part.from_dict(d)
        assert isinstance(restored, AttachmentPart)
        assert restored.attachment.content == b"hello-bytes"
        assert restored.attachment.type == "image/png"

    def test_attachment_part_round_trips_with_url(self):
        from llm.parts import AttachmentPart, Part

        att = llm.Attachment(type="image/png", url="https://example.com/x.png")
        restored = Part.from_dict(AttachmentPart(attachment=att).to_dict())
        assert restored.attachment.url == "https://example.com/x.png"
        assert restored.attachment.type == "image/png"

    def test_tool_result_part_attachments_round_trip(self):
        from llm.parts import ToolResultPart, Part

        att = llm.Attachment(type="text/plain", content=b"xx")
        tr = ToolResultPart(
            name="f",
            output="out",
            tool_call_id="c1",
            attachments=[att],
        )
        restored = Part.from_dict(tr.to_dict())
        assert len(restored.attachments) == 1
        assert restored.attachments[0].content == b"xx"
        assert restored.attachments[0].type == "text/plain"

    def test_stream_assembler_raises_on_incompatible_type_at_same_index(self):
        from llm.parts import StreamEvent

        class M(llm.Model):
            model_id = "m-bad-index"

            def execute(self, prompt, stream, response, conversation):
                yield StreamEvent(
                    type="tool_call_name",
                    chunk="search",
                    part_index=0,
                    tool_call_id="c1",
                )
                yield StreamEvent(type="text", chunk="hi", part_index=0)

        r = M().prompt("x")
        r.text()
        with pytest.raises(ValueError, match="incompatible with prior type"):
            [p for m in r.messages for p in m.parts]

    def test_stream_assembler_allows_compatible_tool_call_events(self):
        from llm.parts import StreamEvent, ToolCallPart

        class M(llm.Model):
            model_id = "m-ok"

            def execute(self, prompt, stream, response, conversation):
                yield StreamEvent(
                    type="tool_call_name",
                    chunk="search",
                    part_index=0,
                    tool_call_id="c1",
                )
                yield StreamEvent(
                    type="tool_call_args",
                    chunk='{"q":"x"}',
                    part_index=0,
                    tool_call_id="c1",
                )

        r = M().prompt("x")
        r.text()
        assert len([p for m in r.messages for p in m.parts]) == 1
        assert isinstance([p for m in r.messages for p in m.parts][0], ToolCallPart)
        assert [p for m in r.messages for p in m.parts][0].arguments == {"q": "x"}

    def test_build_messages_with_tool_call_and_result_parts(
        self, mocked_openai_chat, user_path
    ):
        from llm.parts import ToolCallPart, ToolResultPart
        from llm import user, assistant, tool_message

        model = llm.get_model("gpt-4o-mini")
        model.key = "x"
        response = model.prompt(
            messages=[
                user("search please"),
                assistant(
                    ToolCallPart(
                        name="search",
                        arguments={"q": "x"},
                        tool_call_id="c1",
                    )
                ),
                tool_message(
                    ToolResultPart(
                        tool_call_id="c1",
                        name="search",
                        output="result",
                    )
                ),
                user("thanks"),
            ]
        )
        response.text()
        last_request = mocked_openai_chat.get_requests()[-1]
        messages = json.loads(last_request.content)["messages"]
        assert messages == [
            {"role": "user", "content": "search please"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "c1",
                        "function": {
                            "name": "search",
                            "arguments": '{"q": "x"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
            {"role": "user", "content": "thanks"},
        ]


class TestProviderMetadata:
    """Opaque provider metadata passthrough on parts and StreamEvent."""

    def test_text_part_provider_metadata_round_trip(self):
        from llm.parts import TextPart, Part

        p = TextPart(
            text="hi",
            provider_metadata={"anthropic": {"citations": [{"encrypted_index": "z"}]}},
        )
        d = p.to_dict()
        assert (
            d["provider_metadata"]["anthropic"]["citations"][0]["encrypted_index"]
            == "z"
        )
        restored = Part.from_dict(d)
        assert restored.provider_metadata == p.provider_metadata

    def test_reasoning_part_provider_metadata_round_trip(self):
        from llm.parts import ReasoningPart, Part

        p = ReasoningPart(
            text="thinking",
            provider_metadata={"anthropic": {"signature": "sig-bytes"}},
        )
        restored = Part.from_dict(p.to_dict())
        assert restored.provider_metadata == {"anthropic": {"signature": "sig-bytes"}}

    def test_tool_call_part_provider_metadata_round_trip(self):
        from llm.parts import ToolCallPart, Part

        p = ToolCallPart(
            name="search",
            arguments={"q": "x"},
            tool_call_id="c1",
            provider_metadata={"gemini": {"thoughtSignature": "abc"}},
        )
        restored = Part.from_dict(p.to_dict())
        assert restored.provider_metadata == {"gemini": {"thoughtSignature": "abc"}}

    def test_tool_result_part_provider_metadata_round_trip(self):
        from llm.parts import ToolResultPart, Part

        p = ToolResultPart(
            name="web_search",
            output="ok",
            tool_call_id="c1",
            provider_metadata={
                "anthropic": {
                    "results": [
                        {"url": "https://example.com", "encrypted_content": "blob"}
                    ]
                }
            },
        )
        restored = Part.from_dict(p.to_dict())
        assert (
            restored.provider_metadata["anthropic"]["results"][0]["encrypted_content"]
            == "blob"
        )

    def test_provider_metadata_omitted_when_none(self):
        from llm.parts import TextPart

        assert "provider_metadata" not in TextPart(text="hi").to_dict()

    def test_stream_event_provider_metadata_flows_to_part(self):
        from llm.parts import StreamEvent, ReasoningPart

        class M(llm.Model):
            model_id = "m-sig"

            def execute(self, prompt, stream, response, conversation):
                yield StreamEvent(
                    type="reasoning",
                    chunk="think",
                    part_index=0,
                    provider_metadata={"anthropic": {"signature": "sig-1"}},
                )
                yield StreamEvent(type="reasoning", chunk="ing", part_index=0)

        r = M().prompt("x")
        r.text()
        parts = [p for m in r.messages for p in m.parts]
        assert len(parts) == 1
        assert isinstance(parts[0], ReasoningPart)
        assert parts[0].text == "thinking"
        assert parts[0].provider_metadata == {"anthropic": {"signature": "sig-1"}}

    def test_stream_event_provider_metadata_last_wins_per_key(self):
        from llm.parts import StreamEvent, ToolCallPart

        class M(llm.Model):
            model_id = "m-sig2"

            def execute(self, prompt, stream, response, conversation):
                yield StreamEvent(
                    type="tool_call_name",
                    chunk="f",
                    part_index=0,
                    tool_call_id="c1",
                    provider_metadata={"anthropic": {"signature": "old"}},
                )
                yield StreamEvent(
                    type="tool_call_args",
                    chunk="{}",
                    part_index=0,
                    provider_metadata={
                        "anthropic": {"signature": "new"},
                        "gemini": {"thoughtSignature": "g"},
                    },
                )

        r = M().prompt("x")
        r.text()
        parts = [p for m in r.messages for p in m.parts]
        assert isinstance(parts[0], ToolCallPart)
        assert parts[0].provider_metadata == {
            "anthropic": {"signature": "new"},
            "gemini": {"thoughtSignature": "g"},
        }


class TestProviderMetadataDatabase:
    """provider_metadata is persisted through log_to_db and loaded back."""

    def test_provider_metadata_persisted_and_loaded(self, logs_db):
        from llm.migrations import migrate
        from llm.parts import StreamEvent

        migrate(logs_db)

        model = StreamEventModel()
        model.enqueue(
            [
                StreamEvent(
                    type="reasoning",
                    chunk="think",
                    part_index=0,
                    provider_metadata={"anthropic": {"signature": "sig-r"}},
                ),
                StreamEvent(
                    type="text",
                    chunk="hello",
                    part_index=1,
                    provider_metadata={"anthropic": {"citations": [{"i": "c"}]}},
                ),
                StreamEvent(
                    type="tool_call_name",
                    chunk="search",
                    part_index=2,
                    tool_call_id="c1",
                    provider_metadata={"gemini": {"thoughtSignature": "sig-g"}},
                ),
                StreamEvent(
                    type="tool_call_args",
                    chunk='{"q":"x"}',
                    part_index=2,
                ),
                StreamEvent(
                    type="tool_result",
                    chunk="ok",
                    part_index=3,
                    server_executed=True,
                    tool_call_id="c1",
                    tool_name="search",
                    provider_metadata={"anthropic": {"encrypted_content": "blob"}},
                ),
            ]
        )
        response = model.prompt("q")
        response.text()
        response.log_to_db(logs_db)

        # Load via the messages loader
        loaded_msgs = llm.Response._load_messages_from_db(
            logs_db, response.id, direction="output"
        )
        assert loaded_msgs is not None
        loaded_parts = [p for m in loaded_msgs for p in m.parts]
        loaded_by_type = {type(p).__name__: p for p in loaded_parts}
        assert loaded_by_type["ReasoningPart"].provider_metadata == {
            "anthropic": {"signature": "sig-r"}
        }
        assert loaded_by_type["TextPart"].provider_metadata == {
            "anthropic": {"citations": [{"i": "c"}]}
        }
        assert loaded_by_type["ToolCallPart"].provider_metadata == {
            "gemini": {"thoughtSignature": "sig-g"}
        }
        assert loaded_by_type["ToolResultPart"].provider_metadata == {
            "anthropic": {"encrypted_content": "blob"}
        }

    def test_provider_metadata_persisted_for_input_parts(self, logs_db):
        from llm.migrations import migrate
        from llm.parts import TextPart, ToolCallPart

        migrate(logs_db)

        model = StreamEventModel()
        model.enqueue([])
        from llm import user, assistant

        response = model.prompt(
            messages=[
                user(
                    TextPart(
                        text="hi",
                        provider_metadata={"anthropic": {"x": 1}},
                    )
                ),
                assistant(
                    ToolCallPart(
                        name="f",
                        arguments={},
                        tool_call_id="c1",
                        provider_metadata={"gemini": {"thoughtSignature": "g"}},
                    )
                ),
            ]
        )
        response.text()
        response.log_to_db(logs_db)

        input_msgs = [m for m in logs_db["messages"].rows if m["direction"] == "input"]
        all_part_rows = list(logs_db["message_parts"].rows)
        input_part_rows = [
            p
            for p in all_part_rows
            if any(m["id"] == p["message_id"] for m in input_msgs)
        ]
        pms = [
            json.loads(r["content_json"])["provider_metadata"]
            for r in input_part_rows
            if r["content_json"]
        ]
        assert {"anthropic": {"x": 1}} in pms
        assert {"gemini": {"thoughtSignature": "g"}} in pms


class TestMessageClass:
    """Message dataclass wraps a role + list of parts."""

    def test_message_basic(self):
        from llm import Message
        from llm.parts import TextPart

        m = Message(role="user", parts=[TextPart(text="hi")])
        assert m.role == "user"
        assert len(m.parts) == 1
        assert m.provider_metadata is None

    def test_message_to_dict_and_from_dict_round_trip(self):
        from llm import Message
        from llm.parts import TextPart, ToolCallPart

        m = Message(
            role="assistant",
            parts=[
                TextPart(text="I'll check."),
                ToolCallPart(
                    name="search",
                    arguments={"q": "x"},
                    tool_call_id="c1",
                ),
            ],
            provider_metadata={"anthropic": {"message_id": "m1"}},
        )
        d = m.to_dict()
        assert d["role"] == "assistant"
        assert d["type"] == "message"
        assert len(d["parts"]) == 2
        assert d["provider_metadata"] == {"anthropic": {"message_id": "m1"}}

        restored = Message.from_dict(d)
        assert len(restored.parts) == 2
        assert isinstance(restored.parts[0], TextPart)
        assert restored.parts[0].text == "I'll check."
        assert isinstance(restored.parts[1], ToolCallPart)
        assert restored.parts[1].tool_call_id == "c1"
        assert restored.provider_metadata == {"anthropic": {"message_id": "m1"}}

    def test_message_to_dict_omits_empty_provider_metadata(self):
        from llm import Message

        d = Message(role="user", parts=[]).to_dict()
        assert "provider_metadata" not in d


class TestNormalizeParts:
    def test_string_becomes_text_part(self):
        from llm.parts import normalize_parts, TextPart

        parts = normalize_parts(["hello"])
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "hello"

    def test_attachment_becomes_attachment_part(self):
        from llm.parts import normalize_parts, AttachmentPart

        att = llm.Attachment(type="image/png", content=b"x")
        parts = normalize_parts([att])
        assert len(parts) == 1
        assert isinstance(parts[0], AttachmentPart)
        assert parts[0].attachment is att

    def test_existing_part_passes_through(self):
        from llm.parts import normalize_parts, TextPart

        p = TextPart(text="x")
        assert normalize_parts([p]) == [p]

    def test_list_is_flattened_one_level(self):
        from llm.parts import normalize_parts, TextPart

        inner = [TextPart(text="a"), TextPart(text="b")]
        parts = normalize_parts(["prefix", inner, "suffix"])
        assert [p.text for p in parts] == ["prefix", "a", "b", "suffix"]

    def test_tuple_is_flattened_one_level(self):
        from llm.parts import normalize_parts, TextPart

        inner = (TextPart(text="a"),)
        parts = normalize_parts([inner])
        assert [p.text for p in parts] == ["a"]

    def test_invalid_raises_type_error(self):
        from llm.parts import normalize_parts

        with pytest.raises(TypeError, match="Cannot convert"):
            normalize_parts([123])


class TestRoleHelpers:
    def test_user_helper_normalizes_string(self):
        from llm import user, Message
        from llm.parts import TextPart

        m = user("hello")
        assert isinstance(m, Message)
        assert m.role == "user"
        assert len(m.parts) == 1
        assert isinstance(m.parts[0], TextPart)
        assert m.parts[0].text == "hello"

    def test_assistant_helper_mixes_text_and_tool_call(self):
        from llm import assistant
        from llm.parts import TextPart, ToolCallPart

        tc = ToolCallPart(
            name="get_weather",
            arguments={"location": "Paris"},
            tool_call_id="c1",
        )
        m = assistant("I'll check.", tc)
        assert m.role == "assistant"
        assert len(m.parts) == 2
        assert isinstance(m.parts[0], TextPart)
        assert m.parts[1] is tc

    def test_assistant_helper_flattens_list_of_parts(self):
        from llm import assistant
        from llm.parts import ToolCallPart

        calls = [
            ToolCallPart(
                name="get_weather",
                arguments={"location": "Paris"},
                tool_call_id="c1",
            ),
            ToolCallPart(
                name="get_weather",
                arguments={"location": "Tokyo"},
                tool_call_id="c2",
            ),
        ]
        m = assistant("I'll check both.", calls)
        assert len(m.parts) == 3
        assert m.parts[0].__class__.__name__ == "TextPart"
        assert m.parts[1].tool_call_id == "c1"
        assert m.parts[2].tool_call_id == "c2"

    def test_system_helper(self):
        from llm import system

        m = system("Be concise.")
        assert m.role == "system"
        assert m.parts[0].text == "Be concise."

    def test_tool_message_helper(self):
        from llm import tool_message
        from llm.parts import ToolResultPart

        tr = ToolResultPart(
            name="search",
            output="ok",
            tool_call_id="c1",
        )
        m = tool_message(tr)
        assert m.role == "tool"
        assert m.parts == [tr]

    def test_helper_preserves_message_provider_metadata(self):
        from llm import assistant

        m = assistant("x", provider_metadata={"openai": {"message_id": "m"}})
        assert m.provider_metadata == {"openai": {"message_id": "m"}}

    def test_helpers_exported_from_llm(self):
        import llm

        for name in ("user", "assistant", "system", "tool_message", "Message"):
            assert hasattr(llm, name), f"llm.{name} missing"


class TestMessagesParameter:
    """model.prompt(messages=[...]) is accepted and reaches the provider."""

    def test_messages_simple_text(self, mocked_openai_chat, user_path):
        from llm import user, assistant, system as system_helper

        model = llm.get_model("gpt-4o-mini")
        model.key = "x"
        response = model.prompt(
            messages=[
                system_helper("Answer briefly."),
                user("What is the capital of France?"),
                assistant("Paris."),
                user("And Germany?"),
            ]
        )
        response.text()
        last_request = mocked_openai_chat.get_requests()[-1]
        messages = json.loads(last_request.content)["messages"]
        assert messages == [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "Paris."},
            {"role": "user", "content": "And Germany?"},
        ]

    def test_messages_attribute_is_preserved_on_prompt(self):
        from llm import user, Message

        model = llm.get_model("gpt-4o-mini")
        prompt = llm.Prompt(None, model, messages=[user("hi")])
        assert len(prompt.messages) == 1
        assert isinstance(prompt.messages[0], Message)
        assert prompt.messages[0].role == "user"

    def test_prompt_without_messages_synthesizes_from_legacy_inputs(self):
        """When messages= is not passed, Prompt.messages is synthesized."""
        model = llm.get_model("gpt-4o-mini")
        prompt = llm.Prompt("hi", model)
        assert len(prompt.messages) == 1
        assert prompt.messages[0].role == "user"


class TestPromptMessagesSynthesis:
    """Prompt.messages is always populated — synthesized from legacy inputs if needed."""

    def test_prompt_only(self):
        from llm.parts import TextPart

        model = llm.get_model("gpt-4o-mini")
        prompt = llm.Prompt("hello", model)
        assert len(prompt.messages) == 1
        assert prompt.messages[0].role == "user"
        assert isinstance(prompt.messages[0].parts[0], TextPart)
        assert prompt.messages[0].parts[0].text == "hello"

    def test_system_and_prompt(self):
        model = llm.get_model("gpt-4o-mini")
        prompt = llm.Prompt("hi", model, system="Be brief.")
        assert [m.role for m in prompt.messages] == ["system", "user"]
        assert prompt.messages[0].parts[0].text == "Be brief."
        assert prompt.messages[1].parts[0].text == "hi"

    def test_prompt_with_attachment(self):
        from llm.parts import TextPart, AttachmentPart

        att = llm.Attachment(type="image/png", content=b"x")
        model = llm.get_model("gpt-4o-mini")
        prompt = llm.Prompt("look", model, attachments=[att])
        assert len(prompt.messages) == 1
        assert prompt.messages[0].role == "user"
        assert isinstance(prompt.messages[0].parts[0], TextPart)
        assert isinstance(prompt.messages[0].parts[1], AttachmentPart)

    def test_explicit_messages_override_legacy(self):
        from llm import user

        model = llm.get_model("gpt-4o-mini")
        prompt = llm.Prompt("legacy", model, messages=[user("explicit")])
        assert len(prompt.messages) == 1
        assert prompt.messages[0].parts[0].text == "explicit"

    def test_openai_consumes_synthesized_messages(self, mocked_openai_chat, user_path):
        """Legacy prompt+system path produces the expected OpenAI messages."""
        model = llm.get_model("gpt-4o-mini")
        model.key = "x"
        r = model.prompt("hello", system="Be brief.")
        r.text()
        messages = json.loads(mocked_openai_chat.get_requests()[-1].content)["messages"]
        assert messages == [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "hello"},
        ]


class TestResponseMessages:
    """response.messages returns a list[Message] wrapping the assembled parts."""

    def test_text_only_response(self):
        from llm.parts import StreamEvent, TextPart
        from llm import Message

        class M(llm.Model):
            model_id = "m-rm1"

            def execute(self, prompt, stream, response, conversation):
                yield StreamEvent(type="text", chunk="hi", part_index=0)

        r = M().prompt("x")
        r.text()
        msgs = r.messages
        assert len(msgs) == 1
        assert isinstance(msgs[0], Message)
        assert msgs[0].role == "assistant"
        assert len(msgs[0].parts) == 1
        assert isinstance(msgs[0].parts[0], TextPart)
        assert msgs[0].parts[0].text == "hi"

    def test_text_plus_tool_call_becomes_one_assistant_message(self):
        from llm.parts import StreamEvent

        class M(llm.Model):
            model_id = "m-rm2"

            def execute(self, prompt, stream, response, conversation):
                yield StreamEvent(type="text", chunk="searching", part_index=0)
                yield StreamEvent(
                    type="tool_call_name",
                    chunk="search",
                    part_index=1,
                    tool_call_id="c1",
                )
                yield StreamEvent(
                    type="tool_call_args",
                    chunk='{"q":"x"}',
                    part_index=1,
                    tool_call_id="c1",
                )

        r = M().prompt("x")
        r.text()
        msgs = r.messages
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        assert [type(p).__name__ for p in msgs[0].parts] == [
            "TextPart",
            "ToolCallPart",
        ]

    def test_plain_string_response(self, mock_model):
        mock_model.enqueue(["hello world"])
        r = mock_model.prompt("hi")
        r.text()
        msgs = r.messages
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        assert msgs[0].parts[0].text == "hello world"

    def test_empty_response_has_empty_messages(self, mock_model):
        mock_model.enqueue([""])
        r = mock_model.prompt("hi")
        r.text()
        assert r.messages == []


class TestConversationHistoryViaMessages:
    """OpenAI build_messages reconstructs history via prev_response.messages."""

    def test_two_turn_history(self, httpx_mock, user_path):
        for text in ["Paris.", "Berlin."]:
            httpx_mock.add_response(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "usage": {},
                    "choices": [{"message": {"content": text}}],
                },
                headers={"Content-Type": "application/json"},
            )
        model = llm.get_model("gpt-4o-mini")
        model.key = "x"
        conv = model.conversation()
        r1 = conv.prompt("Capital of France?", system="Be brief.", stream=False)
        r1.text()
        r2 = conv.prompt("And Germany?", stream=False)
        r2.text()
        last_request = httpx_mock.get_requests()[-1]
        messages = json.loads(last_request.content)["messages"]
        assert messages == [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Capital of France?"},
            {"role": "assistant", "content": "Paris."},
            {"role": "user", "content": "And Germany?"},
        ]


class TestDatabaseMessages:
    """Log and load Messages via the messages + message_parts tables."""

    def test_messages_tables_created(self, logs_db):
        from llm.migrations import migrate

        migrate(logs_db)
        assert "messages" in logs_db.table_names()
        assert "message_parts" in logs_db.table_names()

    def test_log_and_load_messages(self, logs_db, mock_model):
        from llm.migrations import migrate

        migrate(logs_db)
        mock_model.enqueue(["Hello world"])
        r = mock_model.prompt("Hi", system="Be brief.")
        r.text()
        r.log_to_db(logs_db)

        # Reload
        row = list(logs_db["responses"].rows)[0]
        loaded = llm.Response.from_row(logs_db, row)
        msgs = loaded.messages
        # Output only — input messages are not loaded back through
        # response.messages (they live on prompt, not response).
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        assert msgs[0].parts[0].text == "Hello world"

    def test_message_rows_structure(self, logs_db, mock_model):
        from llm.migrations import migrate

        migrate(logs_db)
        mock_model.enqueue(["Paris."])
        r = mock_model.prompt("Capital?", system="Be brief.")
        r.text()
        r.log_to_db(logs_db)

        message_rows = list(logs_db["messages"].rows)
        # Two input messages (system, user) + one output (assistant)
        assert len(message_rows) == 3
        roles = [(m["direction"], m["role"]) for m in message_rows]
        assert roles == [
            ("input", "system"),
            ("input", "user"),
            ("output", "assistant"),
        ]
        part_rows = list(logs_db["message_parts"].rows)
        # One part per message
        assert len(part_rows) == 3
