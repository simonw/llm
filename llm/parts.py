"""Part types and StreamEvent for rich model responses.

Parts represent the structured content of model interactions: text, reasoning,
tool calls, tool results, and attachments. StreamEvent wraps streaming chunks
with type information so consumers can distinguish between different kinds of
content as it arrives.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import Attachment


@dataclass
class Part:
    """Base class for all parts."""

    role: str  # "user", "assistant", "system", "tool"

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Part":
        type_ = d.get("type")
        if type_ == "text":
            return TextPart(role=d["role"], text=d["text"])
        elif type_ == "reasoning":
            return ReasoningPart(
                role=d["role"],
                text=d.get("text", ""),
                redacted=d.get("redacted", False),
                token_count=d.get("token_count"),
            )
        elif type_ == "tool_call":
            return ToolCallPart(
                role=d["role"],
                name=d["name"],
                arguments=d["arguments"],
                tool_call_id=d.get("tool_call_id"),
                server_executed=d.get("server_executed", False),
            )
        elif type_ == "tool_result":
            return ToolResultPart(
                role=d["role"],
                name=d["name"],
                output=d["output"],
                tool_call_id=d.get("tool_call_id"),
                server_executed=d.get("server_executed", False),
                exception=d.get("exception"),
            )
        else:
            raise ValueError(f"Unknown part type: {type_!r}")


@dataclass
class TextPart(Part):
    text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "type": "text", "text": self.text}


@dataclass
class ReasoningPart(Part):
    """Reasoning/thinking tokens from the model."""

    text: str = ""
    redacted: bool = False
    token_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "type": "reasoning",
            "text": self.text,
        }
        if self.redacted:
            d["redacted"] = True
        if self.token_count is not None:
            d["token_count"] = self.token_count
        return d


@dataclass
class ToolCallPart(Part):
    """A request by the model to call a tool."""

    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    server_executed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "type": "tool_call",
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.server_executed:
            d["server_executed"] = True
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

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
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
        return d


@dataclass
class AttachmentPart(Part):
    """An inline attachment (image, audio, file)."""

    attachment: Optional[Attachment] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "type": "attachment"}
        if self.attachment:
            att: Dict[str, Any] = {}
            if self.attachment.type:
                att["type"] = self.attachment.type
            if self.attachment.url:
                att["url"] = self.attachment.url
            if self.attachment.path:
                att["path"] = self.attachment.path
            d["attachment"] = att
        return d


@dataclass
class StreamEvent:
    """A streaming event from a model response.

    type: "text", "reasoning", "tool_call_name", "tool_call_args", "tool_result"
    chunk: The raw text fragment
    part_index: Which part this contributes to (monotonically increasing)
    tool_call_id: Set for tool_call events
    server_executed: True for server-side tool calls/results
    """

    type: str
    chunk: str
    part_index: int
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    tool_name: Optional[str] = None
