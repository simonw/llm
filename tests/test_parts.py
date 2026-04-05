"""Tests for Part types, StreamEvent, and Response integration."""
import pytest
import llm


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

        part = TextPart(role="assistant", text="Hello world")
        assert part.role == "assistant"
        assert part.text == "Hello world"

    def test_reasoning_part_creation(self):
        from llm.parts import ReasoningPart

        part = ReasoningPart(role="assistant", text="Let me think...")
        assert part.role == "assistant"
        assert part.text == "Let me think..."
        assert part.redacted is False
        assert part.token_count is None

    def test_reasoning_part_redacted(self):
        from llm.parts import ReasoningPart

        part = ReasoningPart(role="assistant", text="", redacted=True, token_count=150)
        assert part.redacted is True
        assert part.token_count == 150

    def test_tool_call_part_creation(self):
        from llm.parts import ToolCallPart

        part = ToolCallPart(
            role="assistant",
            name="search",
            arguments={"query": "weather"},
            tool_call_id="call_123",
        )
        assert part.role == "assistant"
        assert part.name == "search"
        assert part.arguments == {"query": "weather"}
        assert part.tool_call_id == "call_123"
        assert part.server_executed is False

    def test_tool_result_part_creation(self):
        from llm.parts import ToolResultPart

        part = ToolResultPart(
            role="tool",
            name="search",
            output="Sunny, 72F",
            tool_call_id="call_123",
        )
        assert part.role == "tool"
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
        part = AttachmentPart(role="user", attachment=att)
        assert part.role == "user"
        assert part.attachment is att


class TestPartSerialization:
    def test_text_part_roundtrip(self):
        from llm.parts import TextPart, Part

        part = TextPart(role="user", text="Hello")
        d = part.to_dict()
        assert d == {"role": "user", "type": "text", "text": "Hello"}
        restored = Part.from_dict(d)
        assert isinstance(restored, TextPart)
        assert restored.role == "user"
        assert restored.text == "Hello"

    def test_reasoning_part_roundtrip(self):
        from llm.parts import ReasoningPart, Part

        part = ReasoningPart(role="assistant", text="thinking...")
        d = part.to_dict()
        assert d == {"role": "assistant", "type": "reasoning", "text": "thinking..."}
        restored = Part.from_dict(d)
        assert isinstance(restored, ReasoningPart)
        assert restored.text == "thinking..."
        assert restored.redacted is False

    def test_reasoning_part_redacted_roundtrip(self):
        from llm.parts import ReasoningPart, Part

        part = ReasoningPart(role="assistant", text="", redacted=True, token_count=42)
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
            role="assistant",
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
            role="tool",
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
            Part.from_dict({"role": "user", "type": "unknown_thing"})


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
        """response.parts returns a list of Part objects after completion."""
        from llm.parts import TextPart

        mock_model.enqueue(["Hello", " world"])
        response = mock_model.prompt("hi")
        response.text()  # Force completion
        parts = response.parts
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].role == "assistant"
        assert parts[0].text == "Hello world"

    def test_parts_not_done_forces(self, mock_model):
        """Accessing parts forces the response to complete."""
        from llm.parts import TextPart

        mock_model.enqueue(["Hello"])
        response = mock_model.prompt("hi")
        # Don't call text() or iterate - just access parts directly
        parts = response.parts
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
        parts = response.parts
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
        model.enqueue([
            StreamEvent(type="text", chunk="Hello", part_index=0),
            StreamEvent(type="text", chunk=" world", part_index=0),
        ])
        response = model.prompt("hi")
        chunks = list(response)
        assert chunks == ["Hello", " world"]
        assert response.text() == "Hello world"

    def test_mixed_str_and_stream_events(self):
        """Mix of str and StreamEvent in same execute() works."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue([
            "plain ",
            StreamEvent(type="text", chunk="event", part_index=0),
        ])
        response = model.prompt("hi")
        chunks = list(response)
        assert chunks == ["plain ", "event"]

    def test_reasoning_events_not_in_iter(self):
        """Reasoning StreamEvents are silently filtered from __iter__ but appear in stream_events()."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue([
            StreamEvent(type="reasoning", chunk="Let me think...", part_index=0),
            StreamEvent(type="text", chunk="The answer is 42", part_index=1),
        ])
        response = model.prompt("question")
        # Regular iteration only yields text
        chunks = list(response)
        assert chunks == ["The answer is 42"]

    def test_stream_events_yields_all_types(self):
        """stream_events() yields ALL event types including reasoning."""
        from llm.parts import StreamEvent

        model = StreamEventModel()
        model.enqueue([
            StreamEvent(type="reasoning", chunk="thinking...", part_index=0),
            StreamEvent(type="text", chunk="answer", part_index=1),
        ])
        response = model.prompt("question")
        events = list(response.stream_events())
        assert len(events) == 2
        assert events[0].type == "reasoning"
        assert events[0].chunk == "thinking..."
        assert events[1].type == "text"
        assert events[1].chunk == "answer"

    def test_parts_assembled_from_stream_events(self):
        """response.parts assembles Part objects from StreamEvents."""
        from llm.parts import StreamEvent, TextPart, ReasoningPart

        model = StreamEventModel()
        model.enqueue([
            StreamEvent(type="reasoning", chunk="Let me ", part_index=0),
            StreamEvent(type="reasoning", chunk="think...", part_index=0),
            StreamEvent(type="text", chunk="The ", part_index=1),
            StreamEvent(type="text", chunk="answer", part_index=1),
        ])
        response = model.prompt("question")
        response.text()  # Force completion
        parts = response.parts
        assert len(parts) == 2
        assert isinstance(parts[0], ReasoningPart)
        assert parts[0].text == "Let me think..."
        assert parts[0].role == "assistant"
        assert isinstance(parts[1], TextPart)
        assert parts[1].text == "The answer"
        assert parts[1].role == "assistant"

    def test_tool_call_parts_assembled(self):
        """Tool call StreamEvents are assembled into ToolCallPart."""
        from llm.parts import StreamEvent, TextPart, ToolCallPart
        import json

        model = StreamEventModel()
        model.enqueue([
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
        ])
        response = model.prompt("what's the weather?")
        response.text()
        parts = response.parts
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
        model.enqueue([
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
        ])
        response = model.prompt("compute")
        response.text()
        parts = response.parts
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
        model.enqueue([
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
        ])
        response = model.prompt("hi")
        chunks = list(response)
        assert chunks == ["searching..."]


@pytest.mark.asyncio
class TestPhase2AsyncStreamEventHandling:
    async def test_async_stream_event_text(self):
        """Async: StreamEvent(type='text') yields str chunks."""
        from llm.parts import StreamEvent

        model = AsyncStreamEventModel()
        model.enqueue([
            StreamEvent(type="text", chunk="Hello", part_index=0),
            StreamEvent(type="text", chunk=" world", part_index=0),
        ])
        response = model.prompt("hi")
        chunks = []
        async for chunk in response:
            chunks.append(chunk)
        assert chunks == ["Hello", " world"]

    async def test_async_reasoning_filtered_from_iter(self):
        """Async: reasoning events filtered from __aiter__."""
        from llm.parts import StreamEvent

        model = AsyncStreamEventModel()
        model.enqueue([
            StreamEvent(type="reasoning", chunk="thinking", part_index=0),
            StreamEvent(type="text", chunk="answer", part_index=1),
        ])
        response = model.prompt("hi")
        chunks = []
        async for chunk in response:
            chunks.append(chunk)
        assert chunks == ["answer"]

    async def test_async_astream_events_all_types(self):
        """Async: astream_events() yields all event types."""
        from llm.parts import StreamEvent

        model = AsyncStreamEventModel()
        model.enqueue([
            StreamEvent(type="reasoning", chunk="thinking", part_index=0),
            StreamEvent(type="text", chunk="answer", part_index=1),
        ])
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
        model.enqueue([
            StreamEvent(type="reasoning", chunk="hmm", part_index=0),
            StreamEvent(type="text", chunk="yes", part_index=1),
        ])
        response = model.prompt("hi")
        await response.text()
        parts = response.parts
        assert len(parts) == 2
        assert isinstance(parts[0], ReasoningPart)
        assert parts[0].text == "hmm"
        assert isinstance(parts[1], TextPart)
        assert parts[1].text == "yes"


# Phase 3: OpenAI plugin StreamEvent integration

import json
import os
from pytest_httpx import IteratorStream

API_KEY = os.environ.get("PYTEST_OPENAI_API_KEY", None) or "badkey"


def _openai_sse_chunks(deltas, usage=None):
    """Build SSE byte chunks from a list of delta dicts."""
    for i, (delta, finish_reason) in enumerate(deltas):
        chunk = {
            "id": "chat-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-5.4-mini",
            "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish_reason}
            ],
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
        from llm.parts import StreamEvent, TextPart

        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks([
                    ({"role": "assistant", "content": ""}, None),
                    ({"content": "Hello"}, None),
                    ({"content": " world"}, None),
                    ({}, "stop"),
                ])
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
        parts = response.parts
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello world"

    def test_openai_iter_still_yields_str(self, httpx_mock):
        """Backward compat: iterating Response still yields str."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks([
                    ({"role": "assistant", "content": ""}, None),
                    ({"content": "Hi"}, None),
                    ({}, "stop"),
                ])
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
        from llm.parts import StreamEvent, ToolCallPart

        httpx_mock.add_response(
            method="POST",
            url="https://api.openai.com/v1/chat/completions",
            stream=IteratorStream(
                _openai_sse_chunks([
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
                ])
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
        parts = response.parts
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

        parts = response.parts
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
        parts = response.parts
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "Hello!"
