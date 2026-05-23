"""Tests for llm.serialization — the TypedDict spec for the JSON-safe
wire form of Message, Part, and Response.

Uses pydantic.TypeAdapter to verify that actual to_dict() output
conforms to the TypedDict annotations. pydantic is already a runtime
dependency.
"""

import json
import pytest
from pydantic import TypeAdapter

import llm
from llm.serialization import (
    AttachmentPartDict,
    MessageDict,
    PartDict,
    ResponseDict,
    ReasoningPartDict,
    TextPartDict,
    ToolCallPartDict,
    ToolResultPartDict,
)

# ---- required/optional keys ----------------------------------------


class TestRequiredOptionalKeys:
    def test_message_dict_required_keys(self):
        assert MessageDict.__required_keys__ == {"role", "parts"}
        assert MessageDict.__optional_keys__ == {"provider_metadata"}

    def test_text_part_dict_required_keys(self):
        assert TextPartDict.__required_keys__ == {"type", "text"}
        assert TextPartDict.__optional_keys__ == {"provider_metadata"}

    def test_reasoning_part_dict_required_keys(self):
        assert ReasoningPartDict.__required_keys__ == {"type", "text"}
        assert ReasoningPartDict.__optional_keys__ == {
            "redacted",
            "provider_metadata",
        }

    def test_tool_call_part_dict_required_keys(self):
        assert ToolCallPartDict.__required_keys__ == {"type", "name", "arguments"}
        assert ToolCallPartDict.__optional_keys__ == {
            "tool_call_id",
            "server_executed",
            "provider_metadata",
        }

    def test_tool_result_part_dict_required_keys(self):
        assert ToolResultPartDict.__required_keys__ == {"type", "name", "output"}
        assert ToolResultPartDict.__optional_keys__ == {
            "tool_call_id",
            "server_executed",
            "exception",
            "attachments",
            "provider_metadata",
        }

    def test_attachment_part_dict_required_keys(self):
        assert AttachmentPartDict.__required_keys__ == {"type"}
        assert AttachmentPartDict.__optional_keys__ == {
            "attachment",
            "provider_metadata",
        }

    def test_response_dict_required_keys(self):
        assert ResponseDict.__required_keys__ == {"model", "prompt", "messages"}
        assert ResponseDict.__optional_keys__ == {"id", "usage", "datetime_utc"}


# ---- to_dict output conforms to the TypedDict ----------------------


class TestPartRoundTrip:
    def _adapter(self, td):
        return TypeAdapter(td)

    def test_text_part_matches(self):
        d = llm.parts.TextPart(text="hello").to_dict()
        self._adapter(TextPartDict).validate_python(d)

    def test_text_part_with_provider_metadata_matches(self):
        d = llm.parts.TextPart(
            text="hi", provider_metadata={"anthropic": {"cached": True}}
        ).to_dict()
        self._adapter(TextPartDict).validate_python(d)

    def test_reasoning_part_redacted_matches(self):
        d = llm.parts.ReasoningPart(text="", redacted=True).to_dict()
        self._adapter(ReasoningPartDict).validate_python(d)

    def test_reasoning_part_with_signature_matches(self):
        d = llm.parts.ReasoningPart(
            text="thinking...",
            provider_metadata={"anthropic": {"signature": "sig-abc"}},
        ).to_dict()
        self._adapter(ReasoningPartDict).validate_python(d)

    def test_tool_call_part_matches(self):
        d = llm.parts.ToolCallPart(
            name="search", arguments={"q": "x"}, tool_call_id="c1"
        ).to_dict()
        self._adapter(ToolCallPartDict).validate_python(d)

    def test_tool_result_part_matches(self):
        d = llm.parts.ToolResultPart(
            name="search", output="result", tool_call_id="c1"
        ).to_dict()
        self._adapter(ToolResultPartDict).validate_python(d)

    def test_attachment_part_with_url_matches(self):
        att = llm.Attachment(type="image/jpeg", url="https://example.com/cat.jpg")
        d = llm.parts.AttachmentPart(attachment=att).to_dict()
        self._adapter(AttachmentPartDict).validate_python(d)

    def test_attachment_part_with_bytes_matches(self):
        att = llm.Attachment(type="image/png", content=b"\x89PNG...")
        d = llm.parts.AttachmentPart(attachment=att).to_dict()
        self._adapter(AttachmentPartDict).validate_python(d)


class TestPartDiscriminatedUnion:
    def test_text_part_validates_as_part_dict(self):
        d = llm.parts.TextPart(text="hi").to_dict()
        TypeAdapter(PartDict).validate_python(d)

    def test_reasoning_part_validates_as_part_dict(self):
        d = llm.parts.ReasoningPart(text="thinking").to_dict()
        TypeAdapter(PartDict).validate_python(d)

    def test_tool_call_part_validates_as_part_dict(self):
        d = llm.parts.ToolCallPart(name="t", arguments={}, tool_call_id="c1").to_dict()
        TypeAdapter(PartDict).validate_python(d)

    def test_tool_result_part_validates_as_part_dict(self):
        d = llm.parts.ToolResultPart(
            name="t", output="out", tool_call_id="c1"
        ).to_dict()
        TypeAdapter(PartDict).validate_python(d)

    def test_attachment_part_validates_as_part_dict(self):
        att = llm.Attachment(type="image/jpeg", url="http://x")
        d = llm.parts.AttachmentPart(attachment=att).to_dict()
        TypeAdapter(PartDict).validate_python(d)

    def test_unknown_type_rejected(self):
        with pytest.raises(Exception):
            TypeAdapter(PartDict).validate_python({"type": "nonsense", "text": "x"})


class TestMessageDictRoundTrip:
    def test_user_message_matches(self):
        d = llm.user("hi").to_dict()
        TypeAdapter(MessageDict).validate_python(d)

    def test_assistant_with_mixed_parts_matches(self):
        m = llm.Message(
            role="assistant",
            parts=[
                llm.parts.ReasoningPart(
                    text="thinking",
                    provider_metadata={"anthropic": {"signature": "s"}},
                ),
                llm.parts.TextPart(text="answer"),
                llm.parts.ToolCallPart(
                    name="search",
                    arguments={"q": "x"},
                    tool_call_id="c1",
                ),
            ],
        )
        TypeAdapter(MessageDict).validate_python(m.to_dict())

    def test_tool_role_message_with_results_matches(self):
        m = llm.tool_message(
            llm.parts.ToolResultPart(name="s", output="r", tool_call_id="c1"),
        )
        TypeAdapter(MessageDict).validate_python(m.to_dict())


class TestResponseDictRoundTrip:
    def test_mock_response_to_dict_matches(self, mock_model):
        mock_model.enqueue(["answer"])
        r = mock_model.prompt("q")
        r.text()

        d = r.to_dict()
        TypeAdapter(ResponseDict).validate_python(d)

    def test_response_with_reasoning_matches(self, mock_model):
        mock_model.enqueue(
            [
                llm.parts.StreamEvent(
                    type="reasoning",
                    chunk="thinking",
                    part_index=0,
                    provider_metadata={"anthropic": {"signature": "s"}},
                ),
                llm.parts.StreamEvent(type="text", chunk="answer", part_index=1),
            ]
        )
        r = mock_model.prompt("q")
        r.text()

        d = r.to_dict()
        TypeAdapter(ResponseDict).validate_python(d)

    def test_response_with_options_matches(self, mock_model):
        mock_model.enqueue(["ok"])
        r = mock_model.prompt("q", max_tokens=42)
        r.text()

        d = r.to_dict()
        TypeAdapter(ResponseDict).validate_python(d)
        assert d["prompt"].get("options") == {"max_tokens": 42}


# ---- Literal discriminators ----------------------------------------


class TestLiteralDiscriminators:
    """The `type` field on each PartDict is a Literal — that's how
    Pydantic's discriminated unions work. Verify each literal."""

    def test_text_part_literal_is_text(self):
        import typing

        hints = typing.get_type_hints(TextPartDict)
        # Literal["text"] — check the args
        assert typing.get_args(hints["type"]) == ("text",)

    def test_reasoning_part_literal_is_reasoning(self):
        import typing

        hints = typing.get_type_hints(ReasoningPartDict)
        assert typing.get_args(hints["type"]) == ("reasoning",)

    def test_tool_call_part_literal_is_tool_call(self):
        import typing

        hints = typing.get_type_hints(ToolCallPartDict)
        assert typing.get_args(hints["type"]) == ("tool_call",)

    def test_tool_result_part_literal_is_tool_result(self):
        import typing

        hints = typing.get_type_hints(ToolResultPartDict)
        assert typing.get_args(hints["type"]) == ("tool_result",)

    def test_attachment_part_literal_is_attachment(self):
        import typing

        hints = typing.get_type_hints(AttachmentPartDict)
        assert typing.get_args(hints["type"]) == ("attachment",)


# ---- to_dict / from_dict return-type annotations -------------------


class TestAnnotations:
    """Method signatures should advertise the specific TypedDicts."""

    def test_text_part_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.parts.TextPart.to_dict)
        assert hints["return"] is TextPartDict

    def test_reasoning_part_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.parts.ReasoningPart.to_dict)
        assert hints["return"] is ReasoningPartDict

    def test_tool_call_part_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.parts.ToolCallPart.to_dict)
        assert hints["return"] is ToolCallPartDict

    def test_tool_result_part_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.parts.ToolResultPart.to_dict)
        assert hints["return"] is ToolResultPartDict

    def test_attachment_part_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.parts.AttachmentPart.to_dict)
        assert hints["return"] is AttachmentPartDict

    def test_message_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.Message.to_dict)
        assert hints["return"] is MessageDict

    def test_message_from_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.Message.from_dict)
        assert hints["d"] is MessageDict

    def test_response_to_dict_annotation(self):
        import typing

        hints = typing.get_type_hints(llm.Response.to_dict)
        assert hints["return"] is ResponseDict


# ---- End-to-end JSON round-trip validates against schema -----------


class TestEndToEnd:
    def test_json_roundtrip_validates(self, mock_model):
        mock_model.enqueue(["text answer"])
        r = mock_model.prompt("q")
        r.text()

        payload = json.dumps(r.to_dict())
        parsed = json.loads(payload)
        # Parsed dict should still conform to ResponseDict.
        TypeAdapter(ResponseDict).validate_python(parsed)


# ---- to_dict() must not emit keys absent from the TypedDict --------
#
# pydantic's TypeAdapter on a TypedDict silently drops keys that aren't
# declared, so the round-trip tests above will not catch the case where
# .to_dict() starts emitting a brand-new key that nobody added to the
# TypedDict. These tests close that gap by asserting the set of keys
# .to_dict() returns is a subset of the union of required + optional
# keys declared on the corresponding TypedDict.


def _allowed(td):
    return td.__required_keys__ | td.__optional_keys__


class TestNoUndeclaredKeys:
    def test_text_part_keys(self):
        d = llm.parts.TextPart(
            text="hi",
            provider_metadata={"k": "v"},
        ).to_dict()
        assert set(d.keys()) <= _allowed(TextPartDict)

    def test_reasoning_part_keys(self):
        d = llm.parts.ReasoningPart(
            text="t",
            redacted=True,
            provider_metadata={"k": "v"},
        ).to_dict()
        assert set(d.keys()) <= _allowed(ReasoningPartDict)

    def test_tool_call_part_keys(self):
        d = llm.parts.ToolCallPart(
            name="t",
            arguments={"q": "x"},
            tool_call_id="c1",
            server_executed=True,
            provider_metadata={"k": "v"},
        ).to_dict()
        assert set(d.keys()) <= _allowed(ToolCallPartDict)

    def test_tool_result_part_keys(self):
        d = llm.parts.ToolResultPart(
            name="t",
            output="r",
            tool_call_id="c1",
            server_executed=True,
            exception="boom",
            attachments=[llm.Attachment(type="image/png", url="http://x/y.png")],
            provider_metadata={"k": "v"},
        ).to_dict()
        assert set(d.keys()) <= _allowed(ToolResultPartDict)

    def test_attachment_part_keys(self):
        d = llm.parts.AttachmentPart(
            attachment=llm.Attachment(type="image/png", url="http://x/y.png"),
            provider_metadata={"k": "v"},
        ).to_dict()
        assert set(d.keys()) <= _allowed(AttachmentPartDict)

    def test_message_keys(self):
        d = llm.Message(
            role="assistant",
            parts=[llm.parts.TextPart(text="hi")],
            provider_metadata={"k": "v"},
        ).to_dict()
        assert set(d.keys()) <= _allowed(MessageDict)

    def test_response_keys(self, mock_model):
        mock_model.enqueue(["answer"])
        r = mock_model.prompt("q", max_tokens=10)
        r.text()
        d = r.to_dict()
        assert set(d.keys()) <= _allowed(ResponseDict)
        # And the nested prompt sub-dict must conform too.
        from llm.serialization import PromptDict

        assert set(d["prompt"].keys()) <= _allowed(PromptDict)
