import json
import pytest
import llm


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
        part = llm.TextPart(text="hi", provider_metadata={"openai": {"flag": True}})
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part


class TestReasoningPart:
    def test_roundtrip_with_text(self):
        part = llm.ReasoningPart(text="Let me think...")
        restored = llm.Part.from_dict(part.to_dict())
        assert restored == part
        assert restored.text == "Let me think..."
        assert restored.redacted is False

    def test_roundtrip_redacted(self):
        part = llm.ReasoningPart(text="", redacted=True)
        d = part.to_dict()
        assert d["redacted"] is True
        assert "token_count" not in d
        restored = llm.Part.from_dict(d)
        assert restored == part

    def test_no_token_count_field(self):
        # token_count was removed: opaque token totals live on
        # response.token_details, not on the Part.
        with pytest.raises(TypeError):
            llm.ReasoningPart(text="", redacted=True, token_count=150)


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
        part = llm.ToolResultPart(name="search", output="72F sunny", tool_call_id="c1")
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


# Backward compat for plain-str plugins: iterating a Response still
# yields text strings, response.text() still works, self._chunks is
# still populated.


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
        messages = response.messages()
        assert messages == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hello")])
        ]

    def test_empty_response_has_empty_messages(self, mock_model):
        mock_model.enqueue([])
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages() == []


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
        assert response.messages() == [
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
        msgs = response.messages()
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
        part = response.messages()[0].parts[0]
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
            response.messages()  # noqa: B018

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
        part = response.messages()[0].parts[0]
        assert part.provider_metadata == {"anthropic": {"signature": "final"}}

    def test_redacted_reasoning_event_emits_marker_part(self, mock_model):
        # A reasoning StreamEvent with redacted=True yields a
        # ReasoningPart(text="", redacted=True) marker — opaque token
        # totals live on response.token_details, not on the Part.
        events = [
            llm.StreamEvent(type="reasoning", chunk="", redacted=True),
            llm.StreamEvent(type="text", chunk="hi"),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("x")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.ReasoningPart(text="", redacted=True),
            llm.TextPart(text="hi"),
        ]

    def test_redacted_reasoning_hoisted_to_start_when_emitted_late(self, mock_model):
        # Plugins typically learn opaque reasoning happened only when
        # the final usage chunk arrives, so they emit the marker last.
        # The framework hoists redacted reasoning Parts to the start of
        # the assembled message so UIs can render them before content.
        events = [
            llm.StreamEvent(type="text", chunk="hello"),
            llm.StreamEvent(type="reasoning", chunk="", redacted=True),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("x")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.ReasoningPart(text="", redacted=True),
            llm.TextPart(text="hello"),
        ]

    def test_redacted_reasoning_event_default_redacted_is_false(self):
        ev = llm.StreamEvent(type="reasoning", chunk="thinking")
        assert ev.redacted is False


class TestPartIndexAutoAllocation:
    """When part_index is None (the default), the framework groups
    events into Parts using same-family adjacency for text/reasoning
    and tool_call_id for tool calls."""

    def test_streamevent_part_index_defaults_to_none(self):
        ev = llm.StreamEvent(type="text", chunk="hi")
        assert ev.part_index is None

    def test_consecutive_text_concatenates_into_one_part(self, mock_model):
        events = [
            llm.StreamEvent(type="text", chunk="hello "),
            llm.StreamEvent(type="text", chunk="world"),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages()[0].parts == [llm.TextPart(text="hello world")]

    def test_text_then_reasoning_splits_into_two_parts(self, mock_model):
        events = [
            llm.StreamEvent(type="text", chunk="hello"),
            llm.StreamEvent(type="reasoning", chunk="thinking"),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages()[0].parts == [
            llm.TextPart(text="hello"),
            llm.ReasoningPart(text="thinking"),
        ]

    def test_text_tool_call_text_produces_three_parts(self, mock_model):
        events = [
            llm.StreamEvent(type="text", chunk="before"),
            llm.StreamEvent(
                type="tool_call_name",
                chunk="search",
                tool_call_id="c1",
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk='{"q": "x"}',
                tool_call_id="c1",
            ),
            llm.StreamEvent(type="text", chunk="after"),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages()[0].parts == [
            llm.TextPart(text="before"),
            llm.ToolCallPart(name="search", arguments={"q": "x"}, tool_call_id="c1"),
            llm.TextPart(text="after"),
        ]

    def test_tool_call_groups_by_tool_call_id(self, mock_model):
        events = [
            llm.StreamEvent(
                type="tool_call_name",
                chunk="search",
                tool_call_id="c1",
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk='{"q":',
                tool_call_id="c1",
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk='"weather"}',
                tool_call_id="c1",
            ),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages()[0].parts == [
            llm.ToolCallPart(
                name="search",
                arguments={"q": "weather"},
                tool_call_id="c1",
            )
        ]

    def test_parallel_tool_calls_interleaved_by_id(self, mock_model):
        # Two tool calls whose args interleave on the wire — must
        # still produce two distinct ToolCallParts grouped by id.
        events = [
            llm.StreamEvent(type="tool_call_name", chunk="search", tool_call_id="A"),
            llm.StreamEvent(type="tool_call_name", chunk="lookup", tool_call_id="B"),
            llm.StreamEvent(type="tool_call_args", chunk='{"q":"a"}', tool_call_id="A"),
            llm.StreamEvent(type="tool_call_args", chunk='{"k":"b"}', tool_call_id="B"),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.ToolCallPart(name="search", arguments={"q": "a"}, tool_call_id="A"),
            llm.ToolCallPart(name="lookup", arguments={"k": "b"}, tool_call_id="B"),
        ]

    def test_tool_result_is_always_own_part(self, mock_model):
        events = [
            llm.StreamEvent(
                type="tool_call_name",
                chunk="web_search",
                tool_call_id="c1",
                server_executed=True,
            ),
            llm.StreamEvent(
                type="tool_call_args",
                chunk='{"q":"x"}',
                tool_call_id="c1",
                server_executed=True,
            ),
            llm.StreamEvent(
                type="tool_result",
                chunk="results...",
                tool_call_id="c1",
                tool_name="web_search",
                server_executed=True,
            ),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.ToolCallPart(
                name="web_search",
                arguments={"q": "x"},
                tool_call_id="c1",
                server_executed=True,
            ),
            llm.ToolResultPart(
                name="web_search",
                output="results...",
                tool_call_id="c1",
                server_executed=True,
            ),
        ]

    def test_two_reasoning_blocks_split_by_tool_call(self, mock_model):
        # Some providers emit two thinking blocks separated by a tool
        # call — those should yield two ReasoningParts, not one.
        events = [
            llm.StreamEvent(type="reasoning", chunk="first"),
            llm.StreamEvent(type="tool_call_name", chunk="t", tool_call_id="c1"),
            llm.StreamEvent(type="tool_call_args", chunk="{}", tool_call_id="c1"),
            llm.StreamEvent(type="reasoning", chunk="second"),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.ReasoningPart(text="first"),
            llm.ToolCallPart(name="t", arguments={}, tool_call_id="c1"),
            llm.ReasoningPart(text="second"),
        ]

    def test_parallel_tool_calls_without_id_each_get_own_part(self, mock_model):
        # Gemini emits multiple functionCall parts back-to-back without
        # a tool_call_id. Each tool_call_name must allocate a fresh
        # part — otherwise the N tool calls collapse into one with
        # concatenated names and args.
        events = [
            llm.StreamEvent(type="tool_call_name", chunk="store_fact"),
            llm.StreamEvent(type="tool_call_args", chunk='{"fact":"a"}'),
            llm.StreamEvent(type="tool_call_name", chunk="store_fact"),
            llm.StreamEvent(type="tool_call_args", chunk='{"fact":"b"}'),
            llm.StreamEvent(type="tool_call_name", chunk="store_fact"),
            llm.StreamEvent(type="tool_call_args", chunk='{"fact":"c"}'),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.ToolCallPart(name="store_fact", arguments={"fact": "a"}),
            llm.ToolCallPart(name="store_fact", arguments={"fact": "b"}),
            llm.ToolCallPart(name="store_fact", arguments={"fact": "c"}),
        ]

    def test_explicit_part_index_still_works(self, mock_model):
        # Back-compat: plugins that pass explicit part_index should
        # behave exactly as before.
        events = [
            llm.StreamEvent(type="reasoning", chunk="t", part_index=0),
            llm.StreamEvent(type="text", chunk="hi", part_index=1),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        assert response.messages()[0].parts == [
            llm.ReasoningPart(text="t"),
            llm.TextPart(text="hi"),
        ]

    def test_mix_explicit_zero_and_none_for_text_concatenates(self, mock_model):
        # Forcing a single TextPart across non-adjacent text bursts:
        # plugin pins explicit part_index=0 on the wraparound text
        # events, and the tool call in between gets None (auto).
        events = [
            llm.StreamEvent(type="text", chunk="before ", part_index=0),
            llm.StreamEvent(type="tool_call_name", chunk="t", tool_call_id="c1"),
            llm.StreamEvent(type="tool_call_args", chunk="{}", tool_call_id="c1"),
            llm.StreamEvent(type="text", chunk="after", part_index=0),
        ]
        mock_model.enqueue(events)
        response = mock_model.prompt("hi")
        response.text()
        parts = response.messages()[0].parts
        assert parts == [
            llm.TextPart(text="before after"),
            llm.ToolCallPart(name="t", arguments={}, tool_call_id="c1"),
        ]


class TestStreamEventsLiveDuringStreaming:
    """Client code sees events arrive before the response is done"""

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
        mock_model.enqueue([llm.StreamEvent(type="text", chunk="hi", part_index=0)])
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
    async def test_async_messages_after_await(self, async_mock_model):
        async_mock_model.enqueue(["hi"])
        response = async_mock_model.prompt("x")
        await response.text()
        assert await response.messages() == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hi")])
        ]


class TestMessagesIsCallable:
    """response.messages() is a method (matching .text(), .json(),
    .tool_calls()) — invocation forces execution if not yet done.
    """

    def test_sync_messages_is_callable_and_returns_list(self, mock_model):
        mock_model.enqueue(["hi"])
        response = mock_model.prompt("x")
        # No prior .text() or iteration — calling messages() forces
        # execution and returns the assembled list.
        assert response.messages() == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hi")])
        ]

    def test_sync_messages_after_text_returns_same_list(self, mock_model):
        mock_model.enqueue(["hi"])
        response = mock_model.prompt("x")
        response.text()
        assert response.messages() == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hi")])
        ]

    @pytest.mark.asyncio
    async def test_async_messages_is_awaitable(self, async_mock_model):
        async_mock_model.enqueue(["hi"])
        response = async_mock_model.prompt("x")
        # No prior await — `await response.messages()` forces it.
        result = await response.messages()
        assert result == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hi")])
        ]

    @pytest.mark.asyncio
    async def test_async_messages_after_text_returns_same_list(self, async_mock_model):
        async_mock_model.enqueue(["hi"])
        response = async_mock_model.prompt("x")
        await response.text()
        result = await response.messages()
        assert result == [
            llm.Message(role="assistant", parts=[llm.TextPart(text="hi")])
        ]


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
        assert p.messages == [llm.Message(role="user", parts=[llm.TextPart(text="hi")])]

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
                parts=[llm.ToolResultPart(name="t", output="ok", tool_call_id="c1")],
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

    def test_explicit_messages_ignores_prompt_kwarg(self, mock_model):
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
        response = mock_model.prompt(messages=[llm.system("be brief"), llm.user("hi")])
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
    async def test_async_conversation_prompt_accepts_messages(self, async_mock_model):
        async_mock_model.enqueue(["ok"])
        conv = async_mock_model.conversation()
        response = conv.prompt(messages=[llm.user("q")])
        await response.text()
        assert response.prompt.messages == [llm.user("q")]


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

    def test_conversation_second_turn_prompt_messages_has_full_chain(self, mock_model):
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

    def test_conversation_third_turn_includes_everything_before(self, mock_model):
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        mock_model.enqueue(["a3"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1")
        r1.text()
        r2 = conv.prompt("q2")
        r2.text()
        r3 = conv.prompt("q3")
        r3.text()

        assert r3.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
            llm.assistant("a2"),
            llm.user("q3"),
        ]

    def test_conversation_first_turn_chain_is_single_user_message(self, mock_model):
        mock_model.enqueue(["a1"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1")
        r1.text()
        assert r1.prompt.messages == [llm.user("q1")]

    def test_conversation_preserves_reasoning_and_tool_call_parts(self, mock_model):
        """The chain carries reasoning and tool calls from prior turns,
        not just the flat text — required for multi-turn extended
        thinking (Claude) and tool-use round-trips."""
        mock_model.enqueue(
            [
                llm.StreamEvent(type="reasoning", chunk="thinking...", part_index=0),
                llm.StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
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


class TestSqliteRehydrateMessages:
    """After Response.from_row, response.messages() must still yield the
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
        # _chunks carries the text. response.messages() must fall back
        # to synthesizing a TextPart.
        assert rehydrated._stream_events == []
        assert rehydrated.messages() == [
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
        r1 = mock_model.prompt("q1")
        r1.text()
        r2 = r1.reply("q2")
        r2.text()
        r3 = r2.reply("q3")
        r3.text()
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
        r2 = await r1.reply("q2")
        await r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
            llm.user("q2"),
        ]

    def test_reply_with_tool_results_appends_tool_message(self, mock_model):
        # The natural idiom: model.prompt(...) makes tool calls, the
        # caller runs them, then reply(tool_results=...) sends the
        # results back in one call. The chain should grow by a
        # role="tool" message containing ToolResultParts.
        from llm.parts import (
            Message,
            ToolCallPart,
            ToolResultPart,
        )

        # First-turn assistant message has a tool call.
        first_assistant = Message(
            role="assistant",
            parts=[ToolCallPart(name="echo", arguments={"x": 1}, tool_call_id="c1")],
        )

        class ToolCallMock(type(mock_model)):
            supports_tools = True

            def execute(self, prompt, stream, response, conversation):
                # Yield the assistant turn's parts as StreamEvents so
                # response.messages() contains the tool call.
                yield llm.StreamEvent(
                    type="tool_call_name",
                    chunk="echo",
                    tool_call_id="c1",
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 1}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo")
        r1.text()

        tool_results = [llm.ToolResult(name="echo", output="ok", tool_call_id="c1")]
        # The bug we're fixing: this previously silently dropped the
        # tool_results because reply() forwards via messages= and the
        # Prompt synthesis path is bypassed.
        m.enqueue(["follow-up text"])
        r2 = r1.reply(tool_results=tool_results)
        r2.text()
        assert r2.prompt.messages == [
            llm.user("call echo"),
            first_assistant,
            Message(
                role="tool",
                parts=[ToolResultPart(name="echo", output="ok", tool_call_id="c1")],
            ),
        ]

    def test_reply_with_tool_results_and_prompt(self, mock_model):
        from llm.parts import (
            Message,
            ToolCallPart,
            ToolResultPart,
        )

        class ToolCallMock(type(mock_model)):
            supports_tools = True

            def execute(self, prompt, stream, response, conversation):
                yield llm.StreamEvent(
                    type="tool_call_name",
                    chunk="echo",
                    tool_call_id="c1",
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 1}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo")
        r1.text()
        m.enqueue(["follow-up"])
        r2 = r1.reply(
            "now summarise",
            tool_results=[llm.ToolResult(name="echo", output="ok", tool_call_id="c1")],
        )
        r2.text()
        roles = [m.role for m in r2.prompt.messages]
        assert roles == ["user", "assistant", "tool", "user"]
        # tool message goes BEFORE the new user prompt.
        tool_msg = r2.prompt.messages[2]
        assert tool_msg.parts == [
            ToolResultPart(name="echo", output="ok", tool_call_id="c1")
        ]
        assert r2.prompt.messages[3] == llm.user("now summarise")

    def test_reply_auto_executes_tool_calls_when_none_passed(self, mock_model):
        # Zero-arg sugar: response.reply() with tool calls present
        # auto-executes them and threads results back into the chain.
        from llm.parts import Message, ToolResultPart

        executed = []

        def echo(x: int) -> str:
            executed.append(x)
            return f"echo:{x}"

        class ToolCallMock(type(mock_model)):
            supports_tools = True

            def execute(self, prompt, stream, response, conversation):
                response.add_tool_call(
                    llm.ToolCall(name="echo", arguments={"x": 42}, tool_call_id="c1")
                )
                yield llm.StreamEvent(
                    type="tool_call_name", chunk="echo", tool_call_id="c1"
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 42}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo", tools=[echo])
        r1.text()

        m.enqueue(["follow-up"])
        # No tool_results passed — sugar kicks in and auto-executes.
        r2 = r1.reply()
        r2.text()

        assert executed == [42]
        # The tool message landed in the chain.
        roles = [msg.role for msg in r2.prompt.messages]
        assert roles == ["user", "assistant", "tool"]
        tool_msg = r2.prompt.messages[2]
        assert tool_msg.parts == [
            ToolResultPart(name="echo", output="echo:42", tool_call_id="c1")
        ]

    def test_reply_auto_execute_with_prompt(self, mock_model):
        # reply("more text") with tool calls present also auto-executes
        # so the user prompt can land after the tool results.
        executed = []

        def echo(x: int) -> str:
            executed.append(x)
            return "out"

        class ToolCallMock(type(mock_model)):
            supports_tools = True

            def execute(self, prompt, stream, response, conversation):
                response.add_tool_call(
                    llm.ToolCall(name="echo", arguments={"x": 1}, tool_call_id="c1")
                )
                yield llm.StreamEvent(
                    type="tool_call_name", chunk="echo", tool_call_id="c1"
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 1}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo", tools=[echo])
        r1.text()
        m.enqueue(["follow-up"])
        r2 = r1.reply("now summarise")
        r2.text()
        assert executed == [1]
        roles = [msg.role for msg in r2.prompt.messages]
        assert roles == ["user", "assistant", "tool", "user"]

    def test_reply_explicit_tool_results_skips_auto_execute(self, mock_model):
        # Passing tool_results= explicitly overrides the sugar — the
        # tool function does NOT run (caller already ran it / wants
        # custom results).
        executed = []

        def echo(x: int) -> str:
            executed.append(x)
            return "should not see"

        class ToolCallMock(type(mock_model)):
            supports_tools = True

            def execute(self, prompt, stream, response, conversation):
                yield llm.StreamEvent(
                    type="tool_call_name", chunk="echo", tool_call_id="c1"
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 1}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo", tools=[echo])
        r1.text()
        m.enqueue(["follow-up"])
        r2 = r1.reply(
            tool_results=[
                llm.ToolResult(name="echo", output="custom", tool_call_id="c1")
            ]
        )
        r2.text()
        assert executed == []  # echo was NOT called
        tool_msg = r2.prompt.messages[2]
        assert tool_msg.parts[0].output == "custom"

    def test_reply_no_tool_calls_no_tool_message(self, mock_model):
        # reply() on a response without tool calls is unchanged — no
        # tool message gets injected.
        mock_model.enqueue(["a1"])
        mock_model.enqueue(["a2"])
        r1 = mock_model.prompt("q1")
        r1.text()
        r2 = r1.reply()
        r2.text()
        assert r2.prompt.messages == [
            llm.user("q1"),
            llm.assistant("a1"),
        ]

    @pytest.mark.asyncio
    async def test_async_reply_auto_executes_tool_calls(self, async_mock_model):
        # Async reply() is a coroutine; with tool calls present the
        # zero-arg sugar awaits execute_tool_calls() internally.
        from llm.parts import ToolResultPart

        executed = []

        async def echo(x: int) -> str:
            executed.append(x)
            return f"echo:{x}"

        class ToolCallMock(type(async_mock_model)):
            supports_tools = True

            async def execute(self, prompt, stream, response, conversation):
                response.add_tool_call(
                    llm.ToolCall(name="echo", arguments={"x": 7}, tool_call_id="c1")
                )
                yield llm.StreamEvent(
                    type="tool_call_name", chunk="echo", tool_call_id="c1"
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 7}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo", tools=[echo])
        await r1.text()
        m.enqueue(["follow-up"])
        r2 = await r1.reply()
        await r2.text()
        assert executed == [7]
        tool_msg = r2.prompt.messages[2]
        assert tool_msg.parts == [
            ToolResultPart(name="echo", output="echo:7", tool_call_id="c1")
        ]

    @pytest.mark.asyncio
    async def test_async_reply_with_tool_results(self, async_mock_model):
        from llm.parts import (
            Message,
            ToolCallPart,
            ToolResultPart,
        )

        class ToolCallMock(type(async_mock_model)):
            supports_tools = True

            async def execute(self, prompt, stream, response, conversation):
                yield llm.StreamEvent(
                    type="tool_call_name",
                    chunk="echo",
                    tool_call_id="c1",
                )
                yield llm.StreamEvent(
                    type="tool_call_args",
                    chunk='{"x": 1}',
                    tool_call_id="c1",
                )

        m = ToolCallMock()
        r1 = m.prompt("call echo")
        await r1.text()
        m.enqueue(["follow-up"])
        r2 = await r1.reply(
            tool_results=[llm.ToolResult(name="echo", output="ok", tool_call_id="c1")]
        )
        await r2.text()
        assert r2.prompt.messages == [
            llm.user("call echo"),
            Message(
                role="assistant",
                parts=[
                    ToolCallPart(name="echo", arguments={"x": 1}, tool_call_id="c1")
                ],
            ),
            Message(
                role="tool",
                parts=[ToolResultPart(name="echo", output="ok", tool_call_id="c1")],
            ),
        ]


# chain() propagates system across tool-result turns


class TestChainPropagatesSystem:
    """On a tool-result turn within a chain loop, the Prompt must
    carry forward the original system= and system_fragments= so
    adapters that read prompt.system (OpenAI and other
    stateless-per-turn providers) see it on every call."""

    def test_sync_chain_tool_result_turn_preserves_system(self, mock_model):
        # First turn: fake a tool call so the chain iterates.
        tool_call = llm.ToolCall(tool_call_id="c1", name="tick", arguments={})

        class ChainMock(type(mock_model)):
            def execute(self, prompt, stream, response, conversation):
                if not self._queue:
                    yield "done"
                    return
                msgs = self._queue.pop(0)
                for m in msgs:
                    yield m
                if not response._tool_calls:
                    response.add_tool_call(tool_call)

        def tick() -> str:
            "Tick"
            return "tock"

        m = ChainMock()
        m.enqueue(["tool-turn"])  # first response; chain will loop
        m.enqueue(["final"])  # second response, after tool results

        chain = m.chain("q", system="be brief", tools=[tick])
        list(chain.responses())
        # Second response was the tool-result turn.
        second = chain._responses[1]
        assert second.prompt.system == "be brief"

    def test_sync_chain_tool_result_turn_preserves_system_fragments(self, mock_model):
        tool_call = llm.ToolCall(tool_call_id="c1", name="tick", arguments={})

        class ChainMock(type(mock_model)):
            def execute(self, prompt, stream, response, conversation):
                if not self._queue:
                    yield "done"
                    return
                msgs = self._queue.pop(0)
                for m in msgs:
                    yield m
                if not response._tool_calls:
                    response.add_tool_call(tool_call)

        def tick() -> str:
            "Tick"
            return "tock"

        m = ChainMock()
        m.enqueue(["tool-turn"])
        m.enqueue(["final"])

        chain = m.chain(
            "q",
            system="inline sys",
            system_fragments=["fragment A", "fragment B"],
            tools=[tick],
        )
        list(chain.responses())
        second = chain._responses[1]
        # prompt.system concatenates _system + system_fragments; all
        # three strings should be preserved on the tool-result turn.
        assert "inline sys" in second.prompt.system
        assert "fragment A" in second.prompt.system
        assert "fragment B" in second.prompt.system

    @pytest.mark.asyncio
    async def test_async_chain_tool_result_turn_preserves_system(
        self, async_mock_model
    ):
        tool_call = llm.ToolCall(tool_call_id="c1", name="tick", arguments={})

        class AsyncChainMock(type(async_mock_model)):
            supports_tools = True

            async def execute(self, prompt, stream, response, conversation):
                if not self._queue:
                    yield "done"
                    return
                msgs = self._queue.pop(0)
                for m in msgs:
                    yield m
                if not response._tool_calls:
                    response.add_tool_call(tool_call)

        def tick() -> str:
            "Tick"
            return "tock"

        m = AsyncChainMock()
        m.enqueue(["tool-turn"])
        m.enqueue(["final"])

        chain = m.chain("q", system="be brief", tools=[tick])
        responses = []
        async for r in chain.responses():
            responses.append(r)
        second = chain._responses[1]
        assert second.prompt.system == "be brief"


# chain() accepts messages= (parity with prompt())


class TestChainMessagesKwarg:
    def test_conversation_chain_accepts_messages(self, mock_model):
        mock_model.enqueue(["ok"])
        conv = mock_model.conversation()
        chain = conv.chain(messages=[llm.user("explicit")])
        chain.text()
        r1 = chain._responses[0]
        assert r1.prompt.messages == [llm.user("explicit")]

    def test_model_chain_accepts_messages(self, mock_model):
        mock_model.enqueue(["ok"])
        chain = mock_model.chain(messages=[llm.user("explicit")])
        chain.text()
        r1 = chain._responses[0]
        assert r1.prompt.messages == [llm.user("explicit")]

    def test_chain_messages_is_authoritative_over_prompt_kwarg(self, mock_model):
        """Parity with prompt(): when both are passed, messages= wins
        and the prompt= string is not folded into the chain."""
        mock_model.enqueue(["ok"])
        chain = mock_model.chain(
            "ignored text",
            messages=[llm.user("explicit")],
        )
        chain.text()
        r1 = chain._responses[0]
        assert r1.prompt.messages == [llm.user("explicit")]

    def test_chain_with_messages_and_prior_conversation(self, mock_model):
        """Explicit messages= on chain() replaces history reconstruction;
        the chain starts from that exact list."""
        mock_model.enqueue(["first"])
        mock_model.enqueue(["second"])
        conv = mock_model.conversation()
        r1 = conv.prompt("prior")
        r1.text()

        # Now start a chain with explicit messages= — prior turn is
        # ignored (consistent with prompt() behavior).
        chain = conv.chain(messages=[llm.user("fresh start")])
        chain.text()
        first_chain_response = chain._responses[0]
        assert first_chain_response.prompt.messages == [llm.user("fresh start")]

    @pytest.mark.asyncio
    async def test_async_conversation_chain_accepts_messages(self, async_mock_model):
        async_mock_model.enqueue(["ok"])
        conv = async_mock_model.conversation()
        chain = conv.chain(messages=[llm.user("explicit")])
        await chain.text()
        r1 = chain._responses[0]
        assert r1.prompt.messages == [llm.user("explicit")]

    @pytest.mark.asyncio
    async def test_async_model_chain_accepts_messages(self, async_mock_model):
        async_mock_model.enqueue(["ok"])
        chain = async_mock_model.chain(messages=[llm.user("explicit")])
        await chain.text()
        r1 = chain._responses[0]
        assert r1.prompt.messages == [llm.user("explicit")]


# Response.to_dict / Response.from_dict


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
        assert restored.messages() == [llm.assistant("hello")]
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
        mock_model.enqueue(
            [
                llm.StreamEvent(
                    type="reasoning",
                    chunk="thinking...",
                    part_index=0,
                    provider_metadata={"anthropic": {"signature": "sig-abc"}},
                ),
                llm.StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        r = mock_model.prompt("q")
        r.text()

        payload = json.dumps(r.to_dict())
        restored = llm.Response.from_dict(json.loads(payload))

        msgs = restored.messages()
        assert msgs[0].role == "assistant"
        assert isinstance(msgs[0].parts[0], llm.ReasoningPart)
        assert msgs[0].parts[0].text == "thinking..."
        assert msgs[0].parts[0].provider_metadata == {
            "anthropic": {"signature": "sig-abc"}
        }

    def test_from_dict_reply_includes_prior_reasoning_in_chain(self, mock_model):
        """a reply() after from_dict() sends the thinking  signature
        back to the model for multi-turn extended thinking."""
        mock_model.enqueue(
            [
                llm.StreamEvent(
                    type="reasoning",
                    chunk="thinking...",
                    part_index=0,
                    provider_metadata={"anthropic": {"signature": "sig-xyz"}},
                ),
                llm.StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
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
            p for m in chain for p in m.parts if isinstance(p, llm.ReasoningPart)
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
        m = llm.assistant("hi")
        assert llm.Message.from_dict(m.to_dict()) == m


class TestChainResponseStreamEvents:
    def test_sync_chain_stream_events_yields_text_when_no_tools(self, mock_model):
        # Chain with no tool calls is a single-response chain — its
        # stream_events should concatenate from each underlying response.
        mock_model.enqueue([llm.StreamEvent(type="text", chunk="done", part_index=0)])
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


# Client-side serialization round-trip
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
        payload = json.dumps([m.to_dict() for m in r.messages()])
        # Deserialize — no LLM state needed beyond the types.
        restored = [llm.Message.from_dict(d) for d in json.loads(payload)]

        assert restored == r.messages()

    def test_rebuilt_messages_reach_plugin_via_prompt(self, mock_model):
        """Round-trip: serialize messages from turn 1, re-inflate, send
        as messages= to turn 2. The plugin sees the full chain."""
        # Turn 1
        mock_model.enqueue(["turn 1 answer"])
        r1 = mock_model.prompt("turn 1 question")
        r1.text()

        # Persist everything the client cares about.
        history = [llm.user("turn 1 question").to_dict()] + [
            m.to_dict() for m in r1.messages()
        ]
        payload = json.dumps(history)

        # Later — rebuild from the wire form and continue.
        rebuilt = [llm.Message.from_dict(d) for d in json.loads(payload)]
        mock_model.enqueue(["turn 2 answer"])
        r2 = mock_model.prompt(messages=rebuilt + [llm.user("turn 2 question")])
        r2.text()

        # The plugin saw the full structured history on prompt.messages.
        assert r2.prompt.messages == rebuilt + [llm.user("turn 2 question")]
        assert r2.messages() == [llm.assistant("turn 2 answer")]

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
        """The redacted=True marker on a ReasoningPart survives
        round-trip — UIs use it to show that opaque reasoning happened
        in this turn (the actual token count lives on response usage)."""
        msg = llm.Message(
            role="assistant",
            parts=[
                llm.ReasoningPart(text="", redacted=True),
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
