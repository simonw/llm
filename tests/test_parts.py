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
