"""TypedDict spec for the JSON-safe wire form of Part, Message, and Response.

These are the exact shapes returned by ``Part.to_dict()``,
``Message.to_dict()``, and ``Response.to_dict()`` — and accepted by the
matching ``from_dict`` classmethods. They are the canonical wire format;
use them to annotate any code that reads or writes serialized llm data.

Example::

    from llm.serialization import MessageDict

    def save_messages(conn, messages: list[MessageDict]) -> None:
        for m in messages:
            conn.execute(
                "INSERT INTO messages(role, parts_json) VALUES (?, ?)",
                (m["role"], json.dumps(m["parts"])),
            )

Or pair with Pydantic's TypeAdapter for runtime validation::

    from pydantic import TypeAdapter
    from llm.serialization import MessageDict

    msg = TypeAdapter(MessageDict).validate_python(incoming_dict)

Or export JSON Schema for cross-language consumers::

    schema = TypeAdapter(MessageDict).json_schema()

The TypedDicts are erased at runtime — zero overhead. ``NotRequired``
keys may be absent from a serialized payload; required keys must
always be present.
"""

from typing import Any, Dict, List, Literal, Union

# NotRequired moved to typing in 3.11; use typing_extensions for 3.10
# support. typing_extensions is a transitive dep via pydantic.
from typing_extensions import NotRequired, TypedDict


__all__ = [
    "AttachmentDict",
    "AttachmentPartDict",
    "MessageDict",
    "PartDict",
    "PromptDict",
    "ReasoningPartDict",
    "ResponseDict",
    "TextPartDict",
    "ToolCallPartDict",
    "ToolResultPartDict",
    "UsageDict",
]


# ---- Attachment payload (nested inside AttachmentPartDict + tool results) ----


class AttachmentDict(TypedDict, total=False):
    """Nested attachment payload. All fields optional — an Attachment
    may carry a type, a url, a path, and/or base64-encoded content.
    """

    type: str
    url: str
    path: str
    # base64-encoded bytes when the attachment was constructed with raw
    # content= bytes.
    content: str


# ---- Per-Part TypedDicts (discriminated by the `type` field) -----------------


class TextPartDict(TypedDict):
    type: Literal["text"]
    text: str
    provider_metadata: NotRequired[Dict[str, Any]]


class ReasoningPartDict(TypedDict):
    type: Literal["reasoning"]
    text: str
    # Redacted reasoning: text is "" and token_count carries the opaque
    # count reported by the provider (OpenAI GPT-5, Gemini thinking).
    redacted: NotRequired[bool]
    token_count: NotRequired[int]
    provider_metadata: NotRequired[Dict[str, Any]]


class ToolCallPartDict(TypedDict):
    type: Literal["tool_call"]
    name: str
    arguments: Dict[str, Any]
    tool_call_id: NotRequired[str]
    # True for provider-executed calls (Anthropic web search, Gemini code
    # execution). Client echoes the block back as-is on next turn.
    server_executed: NotRequired[bool]
    provider_metadata: NotRequired[Dict[str, Any]]


class ToolResultPartDict(TypedDict):
    type: Literal["tool_result"]
    name: str
    output: str
    tool_call_id: NotRequired[str]
    server_executed: NotRequired[bool]
    exception: NotRequired[str]
    attachments: NotRequired[List[AttachmentDict]]
    provider_metadata: NotRequired[Dict[str, Any]]


class AttachmentPartDict(TypedDict):
    type: Literal["attachment"]
    attachment: NotRequired[AttachmentDict]
    provider_metadata: NotRequired[Dict[str, Any]]


PartDict = Union[
    TextPartDict,
    ReasoningPartDict,
    ToolCallPartDict,
    ToolResultPartDict,
    AttachmentPartDict,
]
"""Discriminated union of Part dict shapes. Use with
``pydantic.TypeAdapter(PartDict)`` to validate / dispatch by ``type``.
"""


# ---- Message ----------------------------------------------------------------


class MessageDict(TypedDict):
    """JSON-safe form of ``llm.Message``.

    ``role`` is one of "user", "assistant", "system", "tool" in practice
    — typed as ``str`` here to leave room for provider-specific values.
    """

    role: str
    parts: List[PartDict]
    provider_metadata: NotRequired[Dict[str, Any]]


# ---- Response + nested shapes -----------------------------------------------


class PromptDict(TypedDict):
    """The ``prompt`` sub-dict of ``Response.to_dict()`` — captures the
    full input chain that was sent for this turn plus any options that
    apply."""

    messages: List[MessageDict]
    options: NotRequired[Dict[str, Any]]
    system: NotRequired[str]


class UsageDict(TypedDict, total=False):
    """Optional usage block on ``ResponseDict``. All fields optional;
    providers vary in which they report."""

    input: int
    output: int
    details: Dict[str, Any]


class ResponseDict(TypedDict):
    """JSON-safe form of ``llm.Response`` — everything needed for
    ``Response.from_dict`` to rehydrate and ``response.reply()`` to
    continue a conversation across a process boundary.
    """

    model: str
    prompt: PromptDict
    messages: List[MessageDict]
    # Audit fields — present on a freshly-serialized response, optional
    # on hand-constructed ones.
    id: NotRequired[str]
    usage: NotRequired[UsageDict]
    datetime_utc: NotRequired[str]
