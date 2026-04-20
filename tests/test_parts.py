"""Tests for Part, Message, StreamEvent and the constructor helpers.

Phase 1 covers the in-memory value types and JSON round-trip only.
No Response / streaming / plugin integration yet.
"""

import json
import pytest

import llm


# -- Exports ------------------------------------------------------------


class TestExports:
    def test_llm_exports_part_types(self):
        assert llm.Part is not None
        assert llm.TextPart is not None
        assert llm.ReasoningPart is not None
        assert llm.ToolCallPart is not None
        assert llm.ToolResultPart is not None
        assert llm.AttachmentPart is not None
        assert llm.Message is not None
        assert llm.StreamEvent is not None

    def test_llm_exports_constructor_helpers(self):
        assert callable(llm.user)
        assert callable(llm.assistant)
        assert callable(llm.system)
        assert callable(llm.tool_message)


# -- Part subclasses ----------------------------------------------------


class TestTextPart:
    def test_roundtrip(self):
        part = llm.TextPart(text="Hello world")
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part
        assert isinstance(restored, llm.TextPart)
        assert restored.text == "Hello world"

    def test_to_dict_shape(self):
        assert llm.TextPart(text="hi").to_dict() == {"type": "text", "text": "hi"}

    def test_with_provider_metadata(self):
        part = llm.TextPart(
            text="hi", provider_metadata={"openai": {"flag": True}}
        )
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part


class TestReasoningPart:
    def test_roundtrip_with_text(self):
        part = llm.ReasoningPart(text="Let me think...")
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part
        assert restored.text == "Let me think..."
        assert restored.redacted is False
        assert restored.token_count is None

    def test_roundtrip_redacted(self):
        part = llm.ReasoningPart(text="", redacted=True, token_count=150)
        d = part.to_dict()
        assert d["redacted"] is True
        assert d["token_count"] == 150
        restored = llm.Part.from_dict(d)
        assert restored == part


class TestToolCallPart:
    def test_roundtrip(self):
        part = llm.ToolCallPart(
            name="search",
            arguments={"query": "weather"},
            tool_call_id="call_123",
        )
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part
        assert restored.server_executed is False

    def test_server_executed_flag_roundtrips(self):
        part = llm.ToolCallPart(
            name="web_search",
            arguments={"q": "x"},
            tool_call_id="c1",
            server_executed=True,
        )
        d = part.to_dict()
        assert d["server_executed"] is True
        restored = llm.Part.from_dict(d)
        assert restored.server_executed is True


class TestToolResultPart:
    def test_roundtrip(self):
        part = llm.ToolResultPart(
            name="search", output="72F sunny", tool_call_id="c1"
        )
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part
        assert restored.exception is None
        assert restored.attachments == []

    def test_with_exception(self):
        part = llm.ToolResultPart(
            name="t", output="", tool_call_id="c1", exception="boom"
        )
        restored = llm.Part.from_dict(part.to_dict())
        assert restored.exception == "boom"


class TestAttachmentPart:
    def test_roundtrip_with_url(self):
        att = llm.Attachment(url="http://example.com/cat.jpg")
        part = llm.AttachmentPart(attachment=att)
        restored = llm.Part.from_dict(part.to_dict())
        assert isinstance(restored, llm.AttachmentPart)
        assert restored.attachment.url == "http://example.com/cat.jpg"

    def test_roundtrip_with_path(self):
        att = llm.Attachment(type="image/jpeg", path="/tmp/x.jpg")
        part = llm.AttachmentPart(attachment=att)
        restored = llm.Part.from_dict(part.to_dict())
        assert restored.attachment.path == "/tmp/x.jpg"
        assert restored.attachment.type == "image/jpeg"

    def test_roundtrip_with_bytes_uses_base64(self):
        raw = b"\x89PNG fake bytes"
        att = llm.Attachment(type="image/png", content=raw)
        part = llm.AttachmentPart(attachment=att)
        d = part.to_dict()
        # Content must be a base64-encoded string in the dict form
        assert isinstance(d["attachment"]["content"], str)
        import base64

        assert base64.b64decode(d["attachment"]["content"]) == raw
        # And round-trip back to the original bytes
        restored = llm.Part.from_dict(d)
        assert restored.attachment.content == raw

    def test_json_serializable(self):
        att = llm.Attachment(type="image/png", content=b"\x00\x01\x02")
        part = llm.AttachmentPart(attachment=att)
        # Must survive json dumps/loads
        restored = llm.Part.from_dict(json.loads(json.dumps(part.to_dict())))
        assert restored.attachment.content == b"\x00\x01\x02"


class TestUnknownPart:
    def test_from_dict_unknown_type_raises(self):
        with pytest.raises(ValueError):
            llm.Part.from_dict({"type": "nonsense"})


class TestRoleNotOnPart:
    def test_text_part_has_no_role_attribute(self):
        # Role lives on Message. Parts are content-only.
        part = llm.TextPart(text="hi")
        assert not hasattr(part, "role")

    def test_reasoning_part_has_no_role_attribute(self):
        assert not hasattr(llm.ReasoningPart(text=""), "role")

    def test_tool_call_part_has_no_role_attribute(self):
        assert not hasattr(
            llm.ToolCallPart(name="t", arguments={}, tool_call_id="c1"),
            "role",
        )


# -- Message ------------------------------------------------------------


class TestMessage:
    def test_roundtrip_simple_user_message(self):
        m = llm.Message(role="user", parts=[llm.TextPart(text="hi")])
        restored = llm.Message.from_dict(m.to_dict())
        assert restored == m

    def test_roundtrip_with_provider_metadata(self):
        m = llm.Message(
            role="assistant",
            parts=[llm.TextPart(text="hi")],
            provider_metadata={"anthropic": {"signature": "abc"}},
        )
        restored = llm.Message.from_dict(m.to_dict())
        assert restored == m

    def test_roundtrip_mixed_parts(self):
        m = llm.Message(
            role="assistant",
            parts=[
                llm.ReasoningPart(text="Thinking"),
                llm.TextPart(text="Result"),
                llm.ToolCallPart(
                    name="search",
                    arguments={"q": "x"},
                    tool_call_id="c1",
                ),
            ],
        )
        restored = llm.Message.from_dict(m.to_dict())
        assert restored == m

    def test_empty_provider_metadata_omitted(self):
        m = llm.Message(role="user", parts=[llm.TextPart(text="x")])
        d = m.to_dict()
        assert "provider_metadata" not in d

    def test_none_and_empty_provider_metadata_equivalent(self):
        m_none = llm.Message(role="user", parts=[llm.TextPart(text="x")])
        m_empty = llm.Message(
            role="user",
            parts=[llm.TextPart(text="x")],
            provider_metadata={},
        )
        # Both serialize the same (empty metadata is omitted)
        assert m_none.to_dict() == m_empty.to_dict()


# -- Constructor helpers -----------------------------------------------


class TestHelpers:
    def test_user_with_string(self):
        m = llm.user("hi")
        assert m.role == "user"
        assert m.parts == [llm.TextPart(text="hi")]

    def test_assistant_with_string(self):
        m = llm.assistant("there")
        assert m.role == "assistant"
        assert m.parts == [llm.TextPart(text="there")]

    def test_system_with_string(self):
        m = llm.system("be brief")
        assert m.role == "system"
        assert m.parts == [llm.TextPart(text="be brief")]

    def test_tool_message_with_part(self):
        tr = llm.ToolResultPart(name="t", output="r", tool_call_id="c1")
        m = llm.tool_message(tr)
        assert m.role == "tool"
        assert m.parts == [tr]

    def test_helper_accepts_attachment(self):
        att = llm.Attachment(url="http://example.com/x.jpg")
        m = llm.user("describe this", att)
        assert m.parts == [
            llm.TextPart(text="describe this"),
            llm.AttachmentPart(attachment=att),
        ]

    def test_helper_accepts_existing_part(self):
        tp = llm.TextPart(text="pre-built")
        m = llm.user(tp)
        assert m.parts == [tp]

    def test_helper_flattens_one_level(self):
        # Nested list gets flattened one level.
        m = llm.user(["one", "two"], "three")
        assert m.parts == [
            llm.TextPart(text="one"),
            llm.TextPart(text="two"),
            llm.TextPart(text="three"),
        ]

    def test_helper_rejects_unknown_types(self):
        with pytest.raises(TypeError):
            llm.user(42)

    def test_helper_with_provider_metadata(self):
        m = llm.assistant("hi", provider_metadata={"openai": {"id": "x"}})
        assert m.provider_metadata == {"openai": {"id": "x"}}


# -- StreamEvent (type only, no Response integration yet) --------------


class TestStreamEvent:
    def test_dataclass_defaults(self):
        ev = llm.StreamEvent(type="text", chunk="hi", part_index=0)
        assert ev.type == "text"
        assert ev.chunk == "hi"
        assert ev.part_index == 0
        assert ev.tool_call_id is None
        assert ev.server_executed is False
        assert ev.tool_name is None
        assert ev.provider_metadata is None
        assert ev.message_index == 0

    def test_all_fields_accepted(self):
        ev = llm.StreamEvent(
            type="tool_call_args",
            chunk='{"q":',
            part_index=2,
            tool_call_id="c1",
            server_executed=True,
            tool_name="search",
            provider_metadata={"openai": {"x": 1}},
            message_index=1,
        )
        assert ev.tool_call_id == "c1"
        assert ev.server_executed is True
        assert ev.tool_name == "search"
        assert ev.provider_metadata == {"openai": {"x": 1}}
        assert ev.message_index == 1


# -- Phase 2: Response streaming scaffolding ----------------------------
#
# Backward compat for plain-str plugins: iterating a Response still
# yields text strings, response.text() still works, self._chunks is
# still populated.
#
# New capabilities:
#   - response.stream_events()  / response.astream_events()
#   - response.messages
#   - _BaseResponse._build_parts()  (internal, tested via .messages)


class TestPlainStrPluginCompat:
    """A plugin that yields plain str must still work unchanged."""

    def test_iter_yields_strings(self, mock_model):
        mock_model.enqueue(["hello", " ", "world"])
        response = mock_model.prompt("hi")
        chunks = list(response)
        assert chunks == ["hello", " ", "world"]

    def test_text_returns_concatenation(self, mock_model):
        mock_model.enqueue(["hello ", "world"])
        response = mock_model.prompt("hi")
        assert response.text() == "hello world"

    def test_chunks_are_preserved(self, mock_model):
        mock_model.enqueue(["a", "b", "c"])
        response = mock_model.prompt("hi")
        response.text()
        assert response._chunks == ["a", "b", "c"]


class TestStreamEventsFromPlainStrPlugin:
    """When a plugin yields plain str, stream_events synthesizes text events."""

    def test_stream_events_yields_text_events(self, mock_model):
        mock_model.enqueue(["hel", "lo"])
        response = mock_model.prompt("hi")
        events = list(response.stream_events())
        assert all(isinstance(e, llm.StreamEvent) for e in events)
        assert [e.type for e in events] == ["text", "text"]
        assert [e.chunk for e in events] == ["hel", "lo"]
        assert all(e.part_index == 0 for e in events)

    def test_response_messages_is_single_assistant_text(self, mock_model):
        mock_model.enqueue(["hello"])
        response = mock_model.prompt("hi")
        response.text()
        messages = response.messages
        assert messages == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hello")])
        ]

    def test_empty_response_has_empty_messages(self, mock_model):
        mock_model.enqueue([])
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages == []


class TestStreamEventsFromStreamEventPlugin:
    """When a plugin yields StreamEvents, they pass through unchanged
    and iteration filters to text only."""

    def test_iter_yields_only_text_chunks(self, mock_model):
        events = [
            llm.StreamEvent(type="reasoning", chunk="think ", part_index=0),
            llm.StreamEvent(type="text", chunk="hel", part_index=1),
            llm.StreamEvent(type="text", chunk="lo", part_index=1),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        chunks = list(response)
        assert chunks == ["hel", "lo"]

    def test_stream_events_yields_all_events(self, mock_model):
        events = [
            llm.StreamEvent(type="reasoning", chunk="t", part_index=0),
            llm.StreamEvent(type="text", chunk="x", part_index=1),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        got = list(response.stream_events())
        assert [e.type for e in got] == ["reasoning", "text"]

    def test_messages_assembles_reasoning_then_text(self, mock_model):
        events = [
            llm.StreamEvent(type="reasoning", chunk="thinking", part_index=0),
            llm.StreamEvent(type="text", chunk="hello", part_index=1),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages == [
            llm.Message(
                role="assistant",
                parts=[
                    llm.ReasoningPart(text="thinking"),
                    llm.TextPart(text="hello"),
                ],
            )
        ]

    def test_tool_call_name_and_args_merge(self, mock_model):
        events = [
            llm.StreamEvent(type="text", chunk="calling", part_index=0),
            llm.StreamEvent(
                type="tool_call_name",
                chunk="search",
                part_index=1,
                tool_call_id="c1",
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk='{"q":',
                part_index=1,
                tool_call_id="c1",
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk='"weather"}',
                part_index=1,
                tool_call_id="c1",
            ),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        msgs = response.messages
        assert len(msgs) == 1
        parts = msgs[0].parts
        assert parts == [
            llm.TextPart(text="calling"),
            llm.ToolCallPart(
                name="search",
                arguments={"q": "weather"},
                tool_call_id="c1",
            ),
        ]

    def test_tool_call_args_unparseable_json_falls_back(self, mock_model):
        events = [
            llm.StreamEvent(
                type="tool_call_name",
                chunk="t",
                part_index=0,
                tool_call_id="c1",
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk="not json",
                part_index=0,
                tool_call_id="c1",
            ),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        part = response.messages[0].parts[0]
        assert part.name == "t"
        assert part.arguments == {"_raw": "not json"}

    def test_family_mismatch_at_same_part_index_raises(self, mock_model):
        events = [
            llm.StreamEvent(type="text", chunk="x", part_index=0),
            llm.StreamEvent(
                type="tool_call_name",
                chunk="t",
                part_index=0,
                tool_call_id="c1",
            ),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        with pytest.raises(ValueError, match="part_index"):
            response.messages  # noqa: B018

    def test_provider_metadata_merges_last_wins(self, mock_model):
        events = [
            llm.StreamEvent(
                type="reasoning",
                chunk="think",
                part_index=0,
                provider_metadata={"anthropic": {"signature": "one"}},
            ),
            llm.StreamEvent(
                type="reasoning",
                chunk="",
                part_index=0,
                provider_metadata={"anthropic": {"signature": "final"}},
            ),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        part = response.messages[0].parts[0]
        assert part.provider_metadata == {"anthropic": {"signature": "final"}}

    def test_reasoning_token_count_prepends_redacted_part(self, mock_model):
        # Plugin reports an opaque reasoning token count — framework
        # prepends a ReasoningPart(redacted=True, token_count=N, text="").
        class CountingModel(type(mock_model)):
            def execute(self, prompt, stream, response, conversation):
                response._reasoning_token_count = 200
                yield llm.StreamEvent(type="text", chunk="hi", part_index=0)

        m = CountingModel()
        response = m.prompt("x")
        response.text()
        parts = response.messages[0].parts
        assert parts[0] == llm.ReasoningPart(
            text="", redacted=True, token_count=200
        )
        assert parts[1] == llm.TextPart(text="hi")


class TestStreamEventsLiveDuringStreaming:
    """Client code sees events arrive before the response is done —
    this is the primary user-facing goal of this phase."""

    def test_events_arrive_before_done(self, mock_model):
        events = [
            llm.StreamEvent(type="reasoning", chunk="t", part_index=0),
            llm.StreamEvent(type="text", chunk="hi", part_index=1),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("x")
        seen = []
        for event in response.stream_events():
            # Record the _done state at the moment we receive the event.
            seen.append((event.type, response._done))
        # Events arrived before _done was set.
        assert [s[0] for s in seen] == ["reasoning", "text"]
        assert all(not done for _type, done in seen)
        # And after the generator is drained, the response is done.
        assert response._done

    def test_stream_events_after_done_replays(self, mock_model):
        mock_model.enqueue(
            [llm.StreamEvent(type="text", chunk="hi", part_index=0)]
        )
        response = mock_model.prompt("x")
        first = list(response.stream_events())
        # Second call replays from the stored events.
        second = list(response.stream_events())
        assert len(first) == 1
        assert [e.type for e in second] == ["text"]
        assert [e.chunk for e in second] == ["hi"]

    def test_plain_str_stream_events_after_done_replays(self, mock_model):
        mock_model.enqueue(["hello"])
        response = mock_model.prompt("x")
        response.text()
        events = list(response.stream_events())
        assert len(events) == 1
        assert events[0].type == "text"
        assert events[0].chunk == "hello"


class TestAsyncStreamEvents:
    @pytest.mark.asyncio
    async def test_async_stream_events_live(self, async_mock_model):
        events = [
            llm.StreamEvent(type="reasoning", chunk="r", part_index=0),
            llm.StreamEvent(type="text", chunk="t", part_index=1),
        ]
        async_mock_model.enqueue(events)
        response = async_mock_model.prompt("x")
        seen_types = []
        async for event in response.astream_events():
            seen_types.append(event.type)
        assert seen_types == ["reasoning", "text"]

    @pytest.mark.asyncio
    async def test_async_iter_yields_only_text(self, async_mock_model):
        events = [
            llm.StreamEvent(type="reasoning", chunk="r", part_index=0),
            llm.StreamEvent(type="text", chunk="hi", part_index=1),
        ]
        async_mock_model.enqueue(events)
        response = async_mock_model.prompt("x")
        chunks = []
        async for chunk in response:
            chunks.append(chunk)
        assert chunks == ["hi"]

    @pytest.mark.asyncio
    async def test_async_messages_requires_await(self, async_mock_model):
        async_mock_model.enqueue(["hi"])
        response = async_mock_model.prompt("x")
        with pytest.raises(ValueError):
            response.messages  # noqa: B018

    @pytest.mark.asyncio
    async def test_async_messages_after_await(self, async_mock_model):
        async_mock_model.enqueue(["hi"])
        response = async_mock_model.prompt("x")
        await response.text()
        assert response.messages == [
            llm.Message(
                role="assistant", parts=[llm.TextPart(text="hi")]
            )
        ]


class TestChainResponseStreamEvents:
    def test_sync_chain_stream_events_yields_text_when_no_tools(
        self, mock_model
    ):
        # Chain with no tool calls is a single-response chain — its
        # stream_events should concatenate from each underlying response.
        mock_model.enqueue(
            [llm.StreamEvent(type="text", chunk="done", part_index=0)]
        )
        chain = mock_model.conversation().chain("q")
        events = list(chain.stream_events())
        assert [e.type for e in events] == ["text"]
        assert [e.chunk for e in events] == ["done"]

    @pytest.mark.asyncio
    async def test_async_chain_astream_events_yields(self, async_mock_model):
        async_mock_model.enqueue(
            [llm.StreamEvent(type="text", chunk="done", part_index=0)]
        )
        chain = async_mock_model.conversation().chain("q")
        events = []
        async for event in chain.astream_events():
            events.append(event)
        assert [e.type for e in events] == ["text"]
