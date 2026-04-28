(serialization)=

# Serialization wire format

LLM provides JSON-safe serialization for `Response`, `Message`, and `Part` objects through `to_dict()` / `from_dict()` methods. The exact shapes of the resulting dicts are defined as `TypedDict`s in the `llm.serialization` module.

These TypedDicts:

- Annotate every `to_dict()` / `from_dict()` method, so static type-checkers, IDE autocomplete, and pydantic's `TypeAdapter` work out of the box.
- Document the keys that may appear in each payload and which are required.
- Are erased at runtime — they have zero overhead and no extra dependencies.

(serialization-using)=

## Using the TypedDicts

Annotate functions that produce or consume serialized payloads:

```python
import json
from pathlib import Path

import llm
from llm.serialization import ResponseDict


def store_turn(payload: ResponseDict) -> None:
    Path("turn.json").write_text(json.dumps(payload))


model = llm.get_model("gpt-5.4-mini")
response = model.prompt("Hi")
response.text()
store_turn(response.to_dict())
```

Validate untrusted payloads at runtime via [pydantic](https://docs.pydantic.dev/):

```python
from pydantic import TypeAdapter
from llm.serialization import MessageDict

incoming = json.loads(some_payload)
validated = TypeAdapter(MessageDict).validate_python(incoming)
```

Or export a JSON Schema for cross-language consumers:

```python
schema = TypeAdapter(MessageDict).json_schema()
```

(serialization-reference)=

## Reference

The `Part` shapes are listed first, since they nest inside the rest. Required keys must be present in every payload; optional keys may be omitted.

<!-- [[[cog
import inspect
from typing import get_type_hints, Union, get_origin, get_args

from llm import serialization

# Render order — nested types first.
ORDER = [
    "AttachmentDict",
    "TextPartDict",
    "ReasoningPartDict",
    "ToolCallPartDict",
    "ToolResultPartDict",
    "AttachmentPartDict",
    "PartDict",
    "MessageDict",
    "PromptDict",
    "UsageDict",
    "ResponseDict",
]


def fmt_type(t):
    """Compact, doc-friendly rendering of a type annotation."""
    s = repr(t)
    # `typing.List[...]` -> `List[...]`; same for Dict/Union/Literal/etc.
    s = s.replace("typing.", "")
    # Drop the package prefix on local types.
    s = s.replace("llm.serialization.", "")
    # `<class 'str'>` -> `str`
    if s.startswith("<class '") and s.endswith("'>"):
        s = s[len("<class '"):-len("'>")]
    return s


def render_typeddict(name):
    cls = getattr(serialization, name)
    # Use __doc__ directly so we don't inherit the `dict` builtin docstring.
    raw = cls.__dict__.get("__doc__")
    doc = inspect.cleandoc(raw) if raw else ""
    # Source docstrings use RST double-backticks; this page is markdown.
    doc = doc.replace("``", "`")
    cog.outl(f"### `{name}`\n")
    if doc:
        for line in doc.split("\n"):
            cog.outl(line)
        cog.outl("")
    hints = get_type_hints(cls)
    required = cls.__required_keys__
    for key, type_ in hints.items():
        marker = "required" if key in required else "optional"
        cog.outl(f"`{key}` *{marker}*")
        cog.outl(f": `{fmt_type(type_)}`")
        cog.outl("")


def render_union(name):
    alias = getattr(serialization, name)
    cog.outl(f"### `{name}`\n")
    cog.outl(
        "Discriminated union of all `Part` dict shapes — every value of "
        "`type` maps to exactly one TypedDict above."
    )
    cog.outl("")
    members = get_args(alias)
    for member in members:
        # Each member's `type` field is a Literal["..."] — pull the value out.
        type_field = get_type_hints(member)["type"]
        literal_value = get_args(type_field)[0]
        cog.outl(f"`type: \"{literal_value}\"`")
        cog.outl(f": `{member.__name__}`")
        cog.outl("")


for entry in ORDER:
    if entry == "PartDict":
        render_union(entry)
    else:
        render_typeddict(entry)
]]] -->
### `AttachmentDict`

Nested attachment payload. All fields optional — an Attachment
may carry a type, a url, a path, and/or base64-encoded content.

`type` *optional*
: `str`

`url` *optional*
: `str`

`path` *optional*
: `str`

`content` *optional*
: `str`

### `TextPartDict`

`type` *required*
: `Literal['text']`

`text` *required*
: `str`

`provider_metadata` *optional*
: `Dict[str, Any]`

### `ReasoningPartDict`

`type` *required*
: `Literal['reasoning']`

`text` *required*
: `str`

`redacted` *optional*
: `bool`

`provider_metadata` *optional*
: `Dict[str, Any]`

### `ToolCallPartDict`

`type` *required*
: `Literal['tool_call']`

`name` *required*
: `str`

`arguments` *required*
: `Dict[str, Any]`

`tool_call_id` *optional*
: `str`

`server_executed` *optional*
: `bool`

`provider_metadata` *optional*
: `Dict[str, Any]`

### `ToolResultPartDict`

`type` *required*
: `Literal['tool_result']`

`name` *required*
: `str`

`output` *required*
: `str`

`tool_call_id` *optional*
: `str`

`server_executed` *optional*
: `bool`

`exception` *optional*
: `str`

`attachments` *optional*
: `List[AttachmentDict]`

`provider_metadata` *optional*
: `Dict[str, Any]`

### `AttachmentPartDict`

`type` *required*
: `Literal['attachment']`

`attachment` *optional*
: `AttachmentDict`

`provider_metadata` *optional*
: `Dict[str, Any]`

### `PartDict`

Discriminated union of all `Part` dict shapes — every value of `type` maps to exactly one TypedDict above.

`type: "text"`
: `TextPartDict`

`type: "reasoning"`
: `ReasoningPartDict`

`type: "tool_call"`
: `ToolCallPartDict`

`type: "tool_result"`
: `ToolResultPartDict`

`type: "attachment"`
: `AttachmentPartDict`

### `MessageDict`

JSON-safe form of `llm.Message`.

`role` is one of "user", "assistant", "system", "tool" in practice
— typed as `str` here to leave room for provider-specific values.

`role` *required*
: `str`

`parts` *required*
: `List[TextPartDict | ReasoningPartDict | ToolCallPartDict | ToolResultPartDict | AttachmentPartDict]`

`provider_metadata` *optional*
: `Dict[str, Any]`

### `PromptDict`

The `prompt` sub-dict of `Response.to_dict()` — captures the
full input chain that was sent for this turn plus any options that
apply.

`messages` *required*
: `List[MessageDict]`

`options` *optional*
: `Dict[str, Any]`

`system` *optional*
: `str`

### `UsageDict`

Optional usage block on `ResponseDict`. All fields optional;
providers vary in which they report.

`input` *optional*
: `int`

`output` *optional*
: `int`

`details` *optional*
: `Dict[str, Any]`

### `ResponseDict`

JSON-safe form of `llm.Response` — everything needed for
`Response.from_dict` to rehydrate and `response.reply()` to
continue a conversation across a process boundary.

`model` *required*
: `str`

`prompt` *required*
: `PromptDict`

`messages` *required*
: `List[MessageDict]`

`id` *optional*
: `str`

`usage` *optional*
: `UsageDict`

`datetime_utc` *optional*
: `str`

<!-- [[[end]]] -->

(serialization-notes)=

## Notes

- All TypedDicts use `NotRequired[...]` for optional keys (via `typing_extensions`, which is a transitive dependency through pydantic). On Python 3.11+ this comes from the standard library `typing` module.
- `AttachmentDict.content` is base64-encoded when the attachment was constructed from raw bytes — that's how binary attachments survive the JSON round-trip.
- `ResponseDict.id`, `usage`, and `datetime_utc` are present on freshly serialized responses but optional on hand-constructed ones — `Response.from_dict()` will accept either.
- The `provider_metadata` key on every Part and Message is opaque by design. It carries provider-specific signatures (Anthropic extended-thinking signatures, Gemini `thoughtSignature`, OpenAI `encrypted_content`) that need to round-trip verbatim across turns. See the "Restoring opaque metadata on subsequent requests" section in {doc}`plugins/advanced-model-plugins` for how plugins use this on the wire.
