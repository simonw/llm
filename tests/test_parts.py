"""Tests for Part types, StreamEvent, and Response integration."""
import pytest
from dataclasses import dataclass

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
