"""Part, Message, and StreamEvent value types.

Parts represent the structured content of model interactions: text,
reasoning, tool calls, tool results, and attachments. A Message wraps a
list of Parts with a role. StreamEvent wraps a streaming chunk with type
information so consumers can distinguish text from reasoning from tool
call fragments as they arrive.

These types are pure values — identity (ids, parent links, storage keys)
is a storage concern that lives elsewhere. Two Messages with identical
content are equal.
"""

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import Attachment
from .serialization import (
    AttachmentDict,
    AttachmentPartDict,
    MessageDict,
    PartDict,
    ReasoningPartDict,
    TextPartDict,
    ToolCallPartDict,
    ToolResultPartDict,
)


def _attachment_to_dict(att: Attachment) -> AttachmentDict:
    d: Dict[str, Any] = {}
    if att.type:
        d["type"] = att.type
    if att.url:
        d["url"] = att.url
    if att.path:
        d["path"] = att.path
    if att.content:
        d["content"] = base64.b64encode(att.content).decode("ascii")
    return d  # type: ignore[return-value]


def _attachment_from_dict(d: AttachmentDict) -> Attachment:
    raw_content = d.get("content")
    content_bytes: Optional[bytes] = None
    if isinstance(raw_content, str):
        content_bytes = base64.b64decode(raw_content)
    return Attachment(
        type=d.get("type"),
        path=d.get("path"),
        url=d.get("url"),
        content=content_bytes,
    )


@dataclass
class Part:
    """Base class for all parts. Role lives on the enclosing Message."""

    def to_dict(self) -> PartDict:
        raise NotImplementedError

    @staticmethod
    def from_dict(d: PartDict) -> "Part":
        if d["type"] == "text":
            return TextPart(
                text=d["text"],
                provider_metadata=d.get("provider_metadata"),
            )
        if d["type"] == "reasoning":
            return ReasoningPart(
                text=d["text"],
                redacted=d.get("redacted", False),
                token_count=d.get("token_count"),
                provider_metadata=d.get("provider_metadata"),
            )
        if d["type"] == "tool_call":
            return ToolCallPart(
                name=d["name"],
                arguments=d["arguments"],
                tool_call_id=d.get("tool_call_id"),
                server_executed=d.get("server_executed", False),
                provider_metadata=d.get("provider_metadata"),
            )
        if d["type"] == "tool_result":
            return ToolResultPart(
                name=d["name"],
                output=d["output"],
                tool_call_id=d.get("tool_call_id"),
                server_executed=d.get("server_executed", False),
                exception=d.get("exception"),
                attachments=[
                    _attachment_from_dict(a) for a in d.get("attachments", [])
                ],
                provider_metadata=d.get("provider_metadata"),
            )
        if d["type"] == "attachment":
            att_dict = d.get("attachment")
            attachment = _attachment_from_dict(att_dict) if att_dict else None
            return AttachmentPart(
                attachment=attachment,
                provider_metadata=d.get("provider_metadata"),
            )
        raise ValueError(f"Unknown part type: {d['type']!r}")


@dataclass
class TextPart(Part):
    text: str = ""
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> TextPartDict:
        d: Dict[str, Any] = {"type": "text", "text": self.text}
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d  # type: ignore[return-value]


@dataclass
class ReasoningPart(Part):
    """Reasoning/thinking tokens from the model.

    `redacted=True, text=""` represents the opaque-token-count case
    (OpenAI GPT-5 series, Gemini) where the provider reports only a
    count, not content.
    """

    text: str = ""
    redacted: bool = False
    token_count: Optional[int] = None
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> ReasoningPartDict:
        d: Dict[str, Any] = {"type": "reasoning", "text": self.text}
        if self.redacted:
            d["redacted"] = True
        if self.token_count is not None:
            d["token_count"] = self.token_count
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d  # type: ignore[return-value]


@dataclass
class ToolCallPart(Part):
    """A request by the model to call a tool.

    `server_executed=True` marks calls the provider executed on the
    server (Anthropic web search, Gemini code execution) rather than
    the LLM tool framework.
    """

    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> ToolCallPartDict:
        d: Dict[str, Any] = {
            "type": "tool_call",
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.server_executed:
            d["server_executed"] = True
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d  # type: ignore[return-value]


@dataclass
class ToolResultPart(Part):
    """The result of a tool call."""

    name: str = ""
    output: str = ""
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    attachments: List[Any] = field(default_factory=list)
    exception: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> ToolResultPartDict:
        d: Dict[str, Any] = {
            "type": "tool_result",
            "name": self.name,
            "output": self.output,
        }
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.server_executed:
            d["server_executed"] = True
        if self.exception is not None:
            d["exception"] = self.exception
        if self.attachments:
            d["attachments"] = [_attachment_to_dict(a) for a in self.attachments]
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d  # type: ignore[return-value]


@dataclass
class AttachmentPart(Part):
    """An inline attachment (image, audio, file)."""

    attachment: Optional[Attachment] = None
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> AttachmentPartDict:
        d: Dict[str, Any] = {"type": "attachment"}
        if self.attachment:
            d["attachment"] = _attachment_to_dict(self.attachment)
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d  # type: ignore[return-value]


@dataclass
class Message:
    """A single turn in a conversation: role + list of parts.

    `parts` contains one or more Part objects. `provider_metadata`
    carries opaque provider-specific data attached to the message as a
    whole; part-level data lives on the individual Part's
    `provider_metadata`.
    """

    role: str
    parts: List[Part] = field(default_factory=list)
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> MessageDict:
        d: Dict[str, Any] = {
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d  # type: ignore[return-value]

    @staticmethod
    def from_dict(d: MessageDict) -> "Message":
        return Message(
            role=d["role"],
            parts=[Part.from_dict(p) for p in d.get("parts", [])],
            provider_metadata=d.get("provider_metadata"),
        )


def normalize_parts(items: Any) -> List[Part]:
    """Normalize helper inputs to a list of Part objects.

    Accepts str (→ TextPart), Attachment (→ AttachmentPart), Part
    (passed through), or a list/tuple of those (flattened one level).
    """
    out: List[Part] = []
    for item in items:
        if isinstance(item, Part):
            out.append(item)
        elif isinstance(item, str):
            out.append(TextPart(text=item))
        elif isinstance(item, Attachment):
            out.append(AttachmentPart(attachment=item))
        elif isinstance(item, (list, tuple)):
            out.extend(normalize_parts(item))
        else:
            raise TypeError(f"Cannot convert {item!r} to an llm Part")
    return out


def system(*items: Any, provider_metadata: Optional[Dict[str, Any]] = None) -> Message:
    "Build a Message with role='system'."
    return Message(
        role="system",
        parts=normalize_parts(items),
        provider_metadata=provider_metadata,
    )


def user(*items: Any, provider_metadata: Optional[Dict[str, Any]] = None) -> Message:
    "Build a Message with role='user'."
    return Message(
        role="user",
        parts=normalize_parts(items),
        provider_metadata=provider_metadata,
    )


def assistant(
    *items: Any, provider_metadata: Optional[Dict[str, Any]] = None
) -> Message:
    "Build a Message with role='assistant'."
    return Message(
        role="assistant",
        parts=normalize_parts(items),
        provider_metadata=provider_metadata,
    )


def tool_message(
    *items: Any, provider_metadata: Optional[Dict[str, Any]] = None
) -> Message:
    "Build a Message with role='tool' (typically wrapping ToolResultParts)."
    return Message(
        role="tool",
        parts=normalize_parts(items),
        provider_metadata=provider_metadata,
    )


@dataclass
class StreamEvent:
    """A streaming event from a model response.

    `part_index` groups events into parts. When left at its default of
    `None`, the framework allocates an index automatically: consecutive
    same-family text/reasoning events concatenate, tool-call events
    group by `tool_call_id`, and `tool_result` always starts its own
    part. Pass an explicit integer only to override the default
    grouping (e.g. forcing a single TextPart across non-adjacent text
    bursts).

    `provider_metadata` carries opaque provider data (Anthropic
    `signature`, Gemini `thoughtSignature`, OpenAI `encrypted_content`)
    that must be echoed back on the next request; the framework merges
    it onto the finalized Part (last non-None wins per top-level key).

    `message_index` is for providers that emit multiple assistant
    messages in a single response (Anthropic server-side tool
    execution); most plugins leave it at 0.
    """

    type: str  # "text" / "reasoning" / "tool_call_name" /
    # "tool_call_args" / "tool_result"
    chunk: str
    part_index: Optional[int] = None
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    tool_name: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None
    message_index: int = 0
