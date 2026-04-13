"""Part types and StreamEvent for rich model responses.

Parts represent the structured content of model interactions: text, reasoning,
tool calls, tool results, and attachments. StreamEvent wraps streaming chunks
with type information so consumers can distinguish between different kinds of
content as it arrives.
"""

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import Attachment


def _attachment_to_dict(att: Attachment) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    if att.type:
        d["type"] = att.type
    if att.url:
        d["url"] = att.url
    if att.path:
        d["path"] = att.path
    if att.content:
        d["content"] = base64.b64encode(att.content).decode("ascii")
    return d


def _attachment_from_dict(d: Dict[str, Any]) -> Attachment:
    content = d.get("content")
    if isinstance(content, str):
        content = base64.b64decode(content)
    return Attachment(
        type=d.get("type"),
        path=d.get("path"),
        url=d.get("url"),
        content=content,
    )


@dataclass
class Part:
    """Base class for all parts. Role lives on the enclosing Message."""

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Part":
        type_ = d.get("type")
        pm = d.get("provider_metadata")
        if type_ == "text":
            return TextPart(text=d["text"], provider_metadata=pm)
        elif type_ == "reasoning":
            return ReasoningPart(
                text=d.get("text", ""),
                redacted=d.get("redacted", False),
                token_count=d.get("token_count"),
                provider_metadata=pm,
            )
        elif type_ == "tool_call":
            return ToolCallPart(
                name=d["name"],
                arguments=d["arguments"],
                tool_call_id=d.get("tool_call_id"),
                server_executed=d.get("server_executed", False),
                provider_metadata=pm,
            )
        elif type_ == "tool_result":
            return ToolResultPart(
                name=d["name"],
                output=d["output"],
                tool_call_id=d.get("tool_call_id"),
                server_executed=d.get("server_executed", False),
                exception=d.get("exception"),
                attachments=[
                    _attachment_from_dict(a) for a in d.get("attachments", [])
                ],
                provider_metadata=pm,
            )
        elif type_ == "attachment":
            att_dict = d.get("attachment")
            attachment = _attachment_from_dict(att_dict) if att_dict else None
            return AttachmentPart(attachment=attachment)
        else:
            raise ValueError(f"Unknown part type: {type_!r}")


@dataclass
class TextPart(Part):
    text: str = ""
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": "text", "text": self.text}
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d


@dataclass
class ReasoningPart(Part):
    """Reasoning/thinking tokens from the model."""

    text: str = ""
    redacted: bool = False
    token_count: Optional[int] = None
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": "reasoning", "text": self.text}
        if self.redacted:
            d["redacted"] = True
        if self.token_count is not None:
            d["token_count"] = self.token_count
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d


@dataclass
class ToolCallPart(Part):
    """A request by the model to call a tool."""

    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
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
        return d


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

    def to_dict(self) -> Dict[str, Any]:
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
        return d


@dataclass
class AttachmentPart(Part):
    """An inline attachment (image, audio, file)."""

    attachment: Optional[Attachment] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": "attachment"}
        if self.attachment:
            d["attachment"] = _attachment_to_dict(self.attachment)
        return d


@dataclass
class Message:
    """A single turn in a conversation: role + list of parts.

    `parts` contains one or more Part objects (TextPart, ToolCallPart, etc).
    `provider_metadata` carries opaque provider-specific data attached to the
    message as a whole (e.g. message-level IDs); part-level data lives on
    the individual Part's own `provider_metadata`.
    """

    role: str
    parts: List[Part] = field(default_factory=list)
    provider_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "type": "message",
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.provider_metadata:
            d["provider_metadata"] = self.provider_metadata
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Message":
        return Message(
            role=d["role"],
            parts=[Part.from_dict(p) for p in d.get("parts", [])],
            provider_metadata=d.get("provider_metadata"),
        )


def normalize_parts(items: Any) -> List[Part]:
    """Normalize helper inputs to a list of Part objects.

    Accepts str, Attachment, Part, or a list/tuple of those (flattened one
    level).
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

    type: "text", "reasoning", "tool_call_name", "tool_call_args", "tool_result"
    chunk: The raw text fragment
    part_index: Which part this contributes to (monotonically increasing)
    tool_call_id: Set for tool_call events
    server_executed: True for server-side tool calls/results
    provider_metadata: Opaque provider-specific data (e.g. Anthropic
        `signature`, Gemini `thoughtSignature`, OpenAI `encrypted_content`)
        that must be echoed back on the next request. Merged onto the
        resulting Part at finalize time (last non-None wins).
    """

    type: str
    chunk: str
    part_index: int
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    tool_name: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None
