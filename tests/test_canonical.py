"""Tests for canonical message serialization and content hashing.

The hash is a contract. Once shipped, changing canonicalization breaks
dedup forever. These snapshot tests pin the wire format — any change that
perturbs them must be a deliberate, versioned migration.
"""

import hashlib
import json

import pytest

from llm._canonical import (
    canonical_message_json,
    message_content_hash,
)
from llm.parts import (
    AttachmentPart,
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from llm.models import Attachment


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestCanonicalMessageJson:
    def test_text_only_user_message(self):
        msg = Message(role="user", parts=[TextPart(text="Hello")])
        out = canonical_message_json(msg)
        assert out == b'{"parts":[{"text":"Hello","type":"text"}],"role":"user"}'

    def test_keys_are_sorted_recursively(self):
        msg = Message(
            role="assistant",
            parts=[TextPart(text="hi")],
            provider_metadata={"z": 1, "a": {"y": 2, "b": 3}},
        )
        out = canonical_message_json(msg).decode("utf-8")
        # Each object's keys must be in sorted order.
        parsed = json.loads(out)
        assert list(parsed.keys()) == sorted(parsed.keys())
        assert list(parsed["provider_metadata"].keys()) == ["a", "z"]
        assert list(parsed["provider_metadata"]["a"].keys()) == ["b", "y"]

    def test_empty_provider_metadata_is_omitted(self):
        msg_none = Message(role="user", parts=[TextPart(text="x")])
        msg_empty = Message(
            role="user", parts=[TextPart(text="x")], provider_metadata={}
        )
        # Both should hash identically — empty == missing.
        assert canonical_message_json(msg_none) == canonical_message_json(msg_empty)
        assert b"provider_metadata" not in canonical_message_json(msg_none)

    def test_no_whitespace_in_output(self):
        msg = Message(role="user", parts=[TextPart(text="hi")])
        out = canonical_message_json(msg)
        assert b", " not in out
        assert b": " not in out

    def test_unicode_not_escaped(self):
        msg = Message(role="user", parts=[TextPart(text="café ☕")])
        out = canonical_message_json(msg)
        # ensure_ascii=False keeps the raw UTF-8 bytes.
        assert "café ☕".encode("utf-8") in out

    def test_include_provider_metadata_false_omits_it(self):
        msg = Message(
            role="assistant",
            parts=[TextPart(text="hi", provider_metadata={"sig": "abc"})],
            provider_metadata={"msg_id": "xyz"},
        )
        with_pm = canonical_message_json(msg, include_provider_metadata=True)
        without_pm = canonical_message_json(msg, include_provider_metadata=False)
        assert b"provider_metadata" in with_pm
        assert b"provider_metadata" not in without_pm
        assert b"sig" not in without_pm
        assert b"msg_id" not in without_pm

    def test_all_part_types_round_trip_into_canonical(self):
        msg = Message(
            role="assistant",
            parts=[
                TextPart(text="answer"),
                ReasoningPart(text="thinking", token_count=12),
                ToolCallPart(
                    name="search",
                    arguments={"q": "weather"},
                    tool_call_id="call_1",
                ),
                ToolResultPart(
                    name="search",
                    output="sunny",
                    tool_call_id="call_1",
                ),
                AttachmentPart(
                    attachment=Attachment(type="image/png", content=b"\x00\x01\x02")
                ),
            ],
        )
        out = canonical_message_json(msg)
        parsed = json.loads(out)
        part_types = [p["type"] for p in parsed["parts"]]
        assert part_types == [
            "text",
            "reasoning",
            "tool_call",
            "tool_result",
            "attachment",
        ]

    def test_attachment_content_is_standard_base64(self):
        msg = Message(
            role="user",
            parts=[AttachmentPart(attachment=Attachment(content=b"\xff\xfe\xfd"))],
        )
        out = canonical_message_json(msg).decode("utf-8")
        # Standard base64 with padding.
        assert '"content":"//79"' in out


class TestMessageContentHash:
    def test_identical_messages_hash_equal(self):
        a = Message(role="user", parts=[TextPart(text="hi")])
        b = Message(role="user", parts=[TextPart(text="hi")])
        assert message_content_hash(a) == message_content_hash(b)

    def test_different_text_hashes_differently(self):
        a = Message(role="user", parts=[TextPart(text="hi")])
        b = Message(role="user", parts=[TextPart(text="bye")])
        assert message_content_hash(a) != message_content_hash(b)

    def test_provider_metadata_affects_hash_by_default(self):
        a = Message(role="assistant", parts=[TextPart(text="x")])
        b = Message(
            role="assistant",
            parts=[TextPart(text="x")],
            provider_metadata={"sig": "abc"},
        )
        assert message_content_hash(a) != message_content_hash(b)

    def test_snapshot_hash_text_only(self):
        """Pinned fixture: if this hash changes, dedup is broken for all
        existing DBs. Treat failure as a contract-breaking signal."""
        msg = Message(role="user", parts=[TextPart(text="Hello, world")])
        assert (
            message_content_hash(msg)
            == _sha256(
                b'{"parts":[{"text":"Hello, world","type":"text"}],"role":"user"}'
            )
        )

    def test_snapshot_hash_with_provider_metadata(self):
        msg = Message(
            role="assistant",
            parts=[TextPart(text="ok")],
            provider_metadata={"beta": 2, "alpha": 1},
        )
        # Keys sorted: alpha before beta.
        expected_json = (
            b'{"parts":[{"text":"ok","type":"text"}],'
            b'"provider_metadata":{"alpha":1,"beta":2},'
            b'"role":"assistant"}'
        )
        assert canonical_message_json(msg) == expected_json
        assert message_content_hash(msg) == _sha256(expected_json)


class TestFloatRejection:
    def test_float_in_message_provider_metadata_raises(self):
        msg = Message(
            role="user",
            parts=[TextPart(text="x")],
            provider_metadata={"temp": 0.7},
        )
        with pytest.raises(TypeError, match="float"):
            message_content_hash(msg)

    def test_float_in_part_provider_metadata_raises(self):
        msg = Message(
            role="user",
            parts=[TextPart(text="x", provider_metadata={"nested": {"f": 1.5}})],
        )
        with pytest.raises(TypeError, match="float"):
            message_content_hash(msg)

    def test_integers_are_fine(self):
        msg = Message(
            role="user",
            parts=[TextPart(text="x")],
            provider_metadata={"count": 42, "nested": {"n": 0}},
        )
        # Should not raise.
        message_content_hash(msg)
