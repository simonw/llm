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


# -- Phase 3: messages= parameter and Prompt.messages synthesis --------


class TestPromptMessagesSynthesis:
    """Prompt.messages constructs a Message list from legacy inputs when
    messages= wasn't passed explicitly."""

    def test_empty_prompt_yields_empty_messages(self, mock_model):
        from llm.models import Prompt

        p = Prompt(None, model=mock_model)
        assert p.messages == []

    def test_prompt_text_synthesizes_user_message(self, mock_model):
        from llm.models import Prompt

        p = Prompt("hi", model=mock_model)
        assert p.messages == [
            llm.Message(role="user", parts=[llm.TextPart(text="hi")])
        ]

    def test_system_and_prompt_synthesizes_two_messages(self, mock_model):
        from llm.models import Prompt

        p = Prompt("hi", model=mock_model, system="be brief")
        assert p.messages == [
            llm.Message(role="system", parts=[llm.TextPart(text="be brief")]),
            llm.Message(role="user", parts=[llm.TextPart(text="hi")]),
        ]

    def test_attachments_join_user_message(self, mock_model):
        from llm.models import Prompt

        att = llm.Attachment(url="http://example.com/a.jpg")
        p = Prompt("look", model=mock_model, attachments=[att])
        assert p.messages == [
            llm.Message(
                role="user",
                parts=[
                    llm.TextPart(text="look"),
                    llm.AttachmentPart(attachment=att),
                ],
            )
        ]

    def test_tool_results_become_tool_role_message(self, mock_model):
        from llm.models import Prompt
        from llm import ToolResult

        tr = ToolResult(name="t", output="ok", tool_call_id="c1")
        p = Prompt(None, model=mock_model, tool_results=[tr])
        assert p.messages == [
            llm.Message(
                role="tool",
                parts=[
                    llm.ToolResultPart(
                        name="t", output="ok", tool_call_id="c1"
                    )
                ],
            )
        ]


class TestPromptMessagesExplicit:
    """When messages= is passed, it's authoritative."""

    def test_explicit_messages_returned_verbatim(self, mock_model):
        from llm.models import Prompt

        explicit = [
            llm.system("x"),
            llm.user("y"),
        ]
        p = Prompt(None, model=mock_model, messages=explicit)
        assert p.messages == explicit

    def test_explicit_messages_ignores_prompt_kwarg(
        self, mock_model
    ):
        """Explicit messages= is authoritative. A prompt= string passed
        alongside is no longer auto-appended — the invariant is that
        prompt.messages equals exactly what the model was sent."""
        from llm.models import Prompt

        explicit = [llm.system("x"), llm.user("prior"), llm.user("follow-up")]
        p = Prompt("ignored text", model=mock_model, messages=explicit)
        assert p.messages == explicit

    def test_explicit_messages_independent_copy(self, mock_model):
        """Mutating the caller's list must not mutate Prompt.messages."""
        from llm.models import Prompt

        explicit = [llm.user("x")]
        p = Prompt(None, model=mock_model, messages=explicit)
        explicit.append(llm.user("later"))
        assert p.messages == [llm.user("x")]


class TestModelPromptMessagesKwarg:
    """model.prompt / conversation.prompt / async counterparts accept
    messages= and the list is observable on the resulting Prompt."""

    def test_model_prompt_accepts_messages(self, mock_model):
        mock_model.enqueue(["ok"])
        response = mock_model.prompt(messages=[llm.user("hi")])
        response.text()
        assert response.prompt.messages == [llm.user("hi")]

    def test_model_prompt_messages_with_system(self, mock_model):
        mock_model.enqueue(["ok"])
        response = mock_model.prompt(
            messages=[llm.system("be brief"), llm.user("hi")]
        )
        response.text()
        assert response.prompt.messages == [
            llm.system("be brief"),
            llm.user("hi"),
        ]

    def test_conversation_prompt_accepts_messages(self, mock_model):
        mock_model.enqueue(["ok"])
        conv = mock_model.conversation()
        response = conv.prompt(messages=[llm.user("q")])
        response.text()
        assert response.prompt.messages == [llm.user("q")]

    @pytest.mark.asyncio
    async def test_async_model_prompt_accepts_messages(self, async_mock_model):
        async_mock_model.enqueue(["ok"])
        response = async_mock_model.prompt(messages=[llm.user("hi")])
        await response.text()
        assert response.prompt.messages == [llm.user("hi")]

    @pytest.mark.asyncio
    async def test_async_conversation_prompt_accepts_messages(
        self, async_mock_model
    ):
        async_mock_model.enqueue(["ok"])
        conv = async_mock_model.conversation()
        response = conv.prompt(messages=[llm.user("q")])
        await response.text()
        assert response.prompt.messages == [llm.user("q")]


# -- Phase 7.1: Conversation passes full chain via messages= ----------
#
# Invariant: response.prompt.messages == exactly what the model was
# sent for this turn, regardless of whether the caller used
# model.prompt(messages=[...]), conversation.prompt("text"), or
# response.reply("text").


class TestConversationFullChainInvariant:
    def test_explicit_messages_is_authoritative_no_prompt_combine(self, mock_model):
        """Explicit messages= is the whole list. If prompt= is ALSO
        passed, it's ignored for messages-building — the caller asked
        for exact control."""
        mock_model.enqueue(["ok"])
        response = mock_model.prompt(
            "this prompt argument is ignored",
            messages=[llm.user("q")],
        )
        response.text()
        assert response.prompt.messages == [llm.user("q")]

    def test_conversation_second_turn_prompt_messages_has_full_chain(
        self, mock_model
    ):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        conv = mock_model.conversation()

        r1 = conv.prompt("q1")
        r1.text()
        r2 = conv.prompt("q2")
        r2.text()

        # r2 was sent the full chain.
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]

    def test_conversation_third_turn_includes_everything_before(
        self, mock_model
    ):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        mock_model.enqueue(["a3"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1"); r1.text()
        r2 = conv.prompt("q2"); r2.text()
        r3 = conv.prompt("q3"); r3.text()

        assert r3.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
            llm.assistant("a2"),
            llm.user("q3"),
        ]

    def test_conversation_first_turn_chain_is_single_user_message(
        self, mock_model
    ):
        mock_model.enqueue(["a1"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1")
        r1.text()
        assert r1.prompt.messages == [llm.user("q1")]

    def test_conversation_preserves_reasoning_and_tool_call_parts(
        self, mock_model
    ):
        """The chain carries reasoning and tool calls from prior turns,
        not just the flat text — required for multi-turn extended
        thinking (Claude) and tool-use round-trips."""
        mock_model.enqueue([
            llm.StreamEvent(type="reasoning", chunk="thinking...", part_index=0),
            llm.StreamEvent(type="text", chunk="answer", part_index=1),
        ])
        mock_model.enqueue(["follow-up answer"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1")
        r1.text()
        r2 = conv.prompt("q2")
        r2.text()

        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.Message(
                role="assistant",
                parts=[
                    llm.ReasoningPart(text="thinking..."),
                    llm.TextPart(text="answer"),
                ],
            ),
            llm.user("q2"),
        ]

    @pytest.mark.asyncio
    async def test_async_conversation_full_chain(self, async_mock_model):
        async_mock_model.enqueue(["a1"])
        async_mock_model.enqueue(["a2"])
        conv = async_mock_model.conversation()
        r1 = conv.prompt("q1")
        await r1.text()
        r2 = conv.prompt("q2")
        await r2.text()

        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]


# -- Regression: rehydrated-from-SQLite response.messages survives ----


class TestSqliteRehydrateMessages:
    """After Response.from_row, response.messages must still yield the
    assistant turn as a TextPart (+ any tool calls). Otherwise
    Conversation.prompt builds a broken chain for `llm -c`.
    """

    def test_from_row_response_messages_synthesized_from_chunks(
        self, mock_model, tmp_path
    ):
        import sqlite_utils
        from llm.migrations import migrate

        mock_model.enqueue(["answer text"])
        r1 = mock_model.prompt("q1")
        r1.text()

        db = sqlite_utils.Database(str(tmp_path / "logs.db"))
        migrate(db)
        r1.log_to_db(db)

        # Rehydrate the response
        row = next(db["responses"].rows)
        rehydrated = llm.Response.from_row(db, row)
        # _stream_events is empty (SQLite doesn't persist those), but
        # _chunks carries the text. response.messages must fall back
        # to synthesizing a TextPart.
        assert rehydrated._stream_events == []
        assert rehydrated.messages == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="answer text")])
        ]

    def test_llm_dash_c_chain_preserves_prior_assistant_turn(
        self, mock_model, tmp_path
    ):
        """End-to-end: a follow-up turn via load_conversation must send
        [user(q1), assistant(a1), user(q2)] — not drop the assistant."""
        import sqlite_utils
        from llm.migrations import migrate
        from llm.cli import load_conversation

        mock_model.enqueue(["first answer"])
        mock_model.enqueue(["second answer"])
        r1 = mock_model.prompt("q1")
        r1.text()

        db_path = tmp_path / "logs.db"
        db = sqlite_utils.Database(str(db_path))
        migrate(db)
        r1.log_to_db(db)

        conv = load_conversation(None, database=str(db_path))
        r2 = conv.prompt("q2")
        r2.text()

        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("first answer"),
            llm.user("q2"),
        ]


# -- Phase 7.3: response.reply() --------------------------------------


class TestResponseReply:
    def test_reply_builds_next_turn_from_this_response(self, mock_model):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        r1 = mock_model.prompt("q1")
        r1.text()

        r2 = r1.reply("q2")
        r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]

    def test_reply_chains(self, mock_model):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        mock_model.enqueue(["a3"])
        r1 = mock_model.prompt("q1"); r1.text()
        r2 = r1.reply("q2"); r2.text()
        r3 = r2.reply("q3"); r3.text()
        assert r3.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
            llm.assistant("a2"),
            llm.user("q3"),
        ]

    def test_reply_no_prompt_reuses_messages_kwarg(self, mock_model):
        """Passing messages= to reply() appends those onto the chain
        in place of a new user string."""
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        r1 = mock_model.prompt("q1")
        r1.text()
        r2 = r1.reply(messages=[llm.user("alt")])
        r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("alt"),
        ]

    def test_reply_from_conversation_response_extends_chain(self, mock_model):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1")
        r1.text()
        r2 = r1.reply("q2")
        r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]

    @pytest.mark.asyncio
    async def test_async_reply(self, async_mock_model):
        async_mock_model.enqueue(["a1"])
        async_mock_model.enqueue(["a2"])
        r1 = async_mock_model.prompt("q1")
        await r1.text()
        r2 = r1.reply("q2")
        await r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]


# -- Phase 7.2: Response.to_dict / Response.from_dict ------------------


class TestResponseToDictFromDict:
    def test_to_dict_captures_chain_and_output(self, mock_model):
        mock_model.enqueue(["hello"])
        r = mock_model.prompt("hi")
        r.text()

        d = r.to_dict()
        assert d["model"] == "mock"
        assert d["prompt"]["messages"] == [llm.user("hi").to_dict()]
        assert d["messages"] == [llm.assistant("hello").to_dict()]

    def test_from_dict_rehydrates_with_messages(self, mock_model):
        mock_model.enqueue(["hello"])
        r = mock_model.prompt("hi")
        r.text()
        payload = json.dumps(r.to_dict())

        restored = llm.Response.from_dict(json.loads(payload))
        assert restored._done
        assert restored.text() == "hello"
        assert restored.messages == [llm.assistant("hello")]
        assert restored.prompt.messages == [llm.user("hi")]

    def test_from_dict_then_reply_continues_conversation(self, mock_model):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        r1 = mock_model.prompt("q1")
        r1.text()

        # Serialize across the process boundary
        payload = json.dumps(r1.to_dict())
        restored = llm.Response.from_dict(json.loads(payload))

        # Continue from the restored response
        r2 = restored.reply("q2")
        r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]

    def test_to_dict_preserves_reasoning_and_signatures(self, mock_model):
        mock_model.enqueue([
            llm.StreamEvent(
                type="reasoning",
                chunk="thinking...",
                part_index=0,
                provider_metadata={"anthropic": {"signature": "sig-abc"}},
            ),
            llm.StreamEvent(type="text", chunk="answer", part_index=1),
        ])
        r = mock_model.prompt("q")
        r.text()

        payload = json.dumps(r.to_dict())
        restored = llm.Response.from_dict(json.loads(payload))

        msgs = restored.messages
        assert msgs[0].role == "assistant"
        assert isinstance(msgs[0].parts[0], llm.ReasoningPart)
        assert msgs[0].parts[0].text == "thinking..."
        assert msgs[0].parts[0].provider_metadata == {
            "anthropic": {"signature": "sig-abc"}
        }

    def test_from_dict_reply_includes_prior_reasoning_in_chain(
        self, mock_model
    ):
        """The thing this entire refactor was about: a reply() after
        from_dict() sends the thinking signature back to the model
        for multi-turn extended thinking."""
        mock_model.enqueue([
            llm.StreamEvent(
                type="reasoning",
                chunk="thinking...",
                part_index=0,
                provider_metadata={"anthropic": {"signature": "sig-xyz"}},
            ),
            llm.StreamEvent(type="text", chunk="answer", part_index=1),
        ])
        mock_model.enqueue(["a2"])
        r1 = mock_model.prompt("q1")
        r1.text()

        payload = json.dumps(r1.to_dict())
        restored = llm.Response.from_dict(json.loads(payload))
        r2 = restored.reply("q2")
        r2.text()

        # The signature must be in the chain sent to the model.
        chain = r2.prompt.messages
        reasoning_parts = [
            p for m in chain for p in m.parts
            if isinstance(p, llm.ReasoningPart)
        ]
        assert len(reasoning_parts) == 1
        assert reasoning_parts[0].provider_metadata == {
            "anthropic": {"signature": "sig-xyz"}
        }

    def test_to_dict_captures_options(self, mock_model):
        mock_model.enqueue(["ok"])
        r = mock_model.prompt("hi", max_tokens=42)
        r.text()

        d = r.to_dict()
        assert d["prompt"]["options"] == {"max_tokens": 42}

    def test_from_dict_options_restored(self, mock_model):
        mock_model.enqueue(["ok"])
        r = mock_model.prompt("hi", max_tokens=42)
        r.text()

        payload = json.dumps(r.to_dict())
        restored = llm.Response.from_dict(json.loads(payload))
        assert restored.prompt.options.max_tokens == 42

    def test_message_from_dict_static_method_unchanged(self):
        # Sanity: Message.from_dict / to_dict keep the Phase 1 contract.
        m = llm.assistant("hi")
        assert llm.Message.from_dict(m.to_dict()) == m


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


# -- Phase 6: Client-side serialization round-trip ---------------------
#
# A library user can persist a conversation by serializing response.messages
# to JSON and later re-inflate it as messages=[...] on a follow-up prompt.
# No SQLite involvement.


class TestClientSerializationRoundTrip:
    def test_response_messages_json_roundtrip(self, mock_model):
        mock_model.enqueue(["hello there"])
        r = mock_model.prompt("hi")
        r.text()

        # Serialize via Message.to_dict / json.dumps
        payload = json.dumps([m.to_dict() for m in r.messages])
        # Deserialize — no LLM state needed beyond the types.
        restored = [llm.Message.from_dict(d) for d in json.loads(payload)]

        assert restored == r.messages

    def test_rebuilt_messages_reach_plugin_via_prompt(self, mock_model):
        """Round-trip: serialize messages from turn 1, re-inflate, send
        as messages= to turn 2. The plugin sees the full chain."""
        # Turn 1
        mock_model.enqueue(["turn 1 answer"])
        r1 = mock_model.prompt("turn 1 question")
        r1.text()

        # Persist everything the client cares about.
        history = [llm.user("turn 1 question").to_dict()] + [
            m.to_dict() for m in r1.messages
        ]
        payload = json.dumps(history)

        # Later — rebuild from the wire form and continue.
        rebuilt = [llm.Message.from_dict(d) for d in json.loads(payload)]
        mock_model.enqueue(["turn 2 answer"])
        r2 = mock_model.prompt(
            messages=rebuilt + [llm.user("turn 2 question")]
        )
        r2.text()

        # The plugin saw the full structured history on prompt.messages.
        assert r2.prompt.messages == rebuilt + [
            llm.user("turn 2 question")
        ]
        assert r2.messages == [llm.assistant("turn 2 answer")]

    def test_roundtrip_preserves_tool_calls_and_results(self, mock_model):
        """Assistant messages with tool calls + subsequent tool role
        messages survive json round-trip intact."""
        messages = [
            llm.user("what's the weather?"),
            llm.assistant(
                "let me check",
                llm.ToolCallPart(
                    name="get_weather",
                    arguments={"city": "Paris"},
                    tool_call_id="c1",
                ),
            ),
            llm.tool_message(
                llm.ToolResultPart(
                    name="get_weather",
                    output="sunny",
                    tool_call_id="c1",
                )
            ),
        ]
        payload = json.dumps([m.to_dict() for m in messages])
        restored = [llm.Message.from_dict(d) for d in json.loads(payload)]
        assert restored == messages

    def test_roundtrip_preserves_redacted_reasoning(self, mock_model):
        """Redacted reasoning parts (opaque token counts) survive
        round-trip — needed for accurate rendering of 'this turn used
        N reasoning tokens'."""
        msg = llm.Message(
            role="assistant",
            parts=[
                llm.ReasoningPart(text="", redacted=True, token_count=150),
                llm.TextPart(text="result"),
            ],
        )
        restored = llm.Message.from_dict(json.loads(json.dumps(msg.to_dict())))
        assert restored == msg

    def test_roundtrip_preserves_provider_metadata(self, mock_model):
        msg = llm.Message(
            role="assistant",
            parts=[
                llm.ReasoningPart(
                    text="thinking",
                    provider_metadata={"anthropic": {"signature": "abc"}},
                ),
                llm.TextPart(text="answer"),
            ],
        )
        restored = llm.Message.from_dict(json.loads(json.dumps(msg.to_dict())))
        assert restored == msg
