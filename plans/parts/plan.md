# Parts Implementation Plan

This is the detailed implementation plan for the LLM "parts" project described in [overview.md](overview.md).

## Design Principles

1. **Backward compatibility is paramount.** LLM has a large plugin ecosystem. Every existing `execute()` method that yields `str` must continue to work without changes. New capabilities are additive — plugins opt in when they're ready.
2. **Two levels of streaming detail.** Simple consumers iterate a Response and get text strings, just like today. Consumers who want the full picture (reasoning tokens, tool call arguments building up, etc.) use a separate `stream_events()` method.
3. **Parts are the single source of truth.** After a response completes, `response.parts` is a list of typed Part objects representing everything that happened. Text, reasoning, tool calls, tool results, attachments — all of it. The existing `.text()`, `.prompt`, `.tool_calls()` etc. become convenience accessors that read from parts.
4. **Storage is just one serialization target.** Parts can round-trip through JSON dicts (for library users who don't use SQLite) or through the database (for CLI logging). Conversation inflation doesn't require a database.

## Part Types

```python
@dataclass
class Part:
    """Base class for all parts."""
    role: str  # "user", "assistant", "system", "tool"

@dataclass
class TextPart(Part):
    text: str

@dataclass
class ReasoningPart(Part):
    """Reasoning/thinking tokens from the model."""
    text: str
    redacted: bool = False  # True when provider hides content but reports token count
    token_count: Optional[int] = None  # For redacted reasoning

@dataclass
class ToolCallPart(Part):
    """A request by the model to call a tool."""
    name: str
    arguments: dict
    tool_call_id: Optional[str] = None
    server_executed: bool = False  # True for server-side tool calls (e.g. Claude code execution)

@dataclass
class ToolResultPart(Part):
    """The result of a tool call."""
    name: str
    output: str
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    attachments: list = field(default_factory=list)
    exception: Optional[str] = None

@dataclass
class AttachmentPart(Part):
    """An inline attachment (image, audio, file)."""
    attachment: Attachment  # Reuses existing Attachment class
```

All Part subclasses will have `to_dict()` and `from_dict()` methods for JSON serialization.

## Streaming: StreamEvent and the Two-Tier API

### StreamEvent

When a model streams back a response, the raw chunks are wrapped in StreamEvent objects:

```python
@dataclass
class StreamEvent:
    type: str         # "text", "reasoning", "tool_call_name", "tool_call_args"
    chunk: str        # The raw text fragment
    part_index: int   # Which part this contributes to (monotonically increasing)
    tool_call_id: Optional[str] = None  # Set for tool_call events
```

`part_index` is a counter that increments each time the model starts producing a new logical part. For example, a response that has reasoning followed by text followed by a tool call would have part_index 0, 1, 2. The Response assembler uses this to know when one part has ended and the next has begun.

### How model plugins yield events

The `execute()` return type changes from `Iterator[str]` to `Iterator[str | StreamEvent]`.

- If a plugin yields plain `str`, Response treats it as `StreamEvent(type="text", chunk=..., part_index=0)`. **This is the full backward compatibility story** — every existing plugin works unchanged.
- Plugins that want to emit rich content yield StreamEvent objects. A plugin can adopt this incrementally: start emitting StreamEvents for reasoning tokens, add tool call streaming later.

The same applies to async: `AsyncGenerator[str, None]` becomes `AsyncGenerator[str | StreamEvent, None]`.

### Consumer API

**Simple (backward compatible):**

```python
# Iterating a Response yields text strings, just like today.
# Reasoning and tool call chunks are silently filtered out.
response = model.prompt("explain quantum computing")
for chunk in response:
    print(chunk, end="")

# .text() works the same as today
print(response.text())
```

**Rich streaming:**

```python
# stream_events() yields every StreamEvent, including reasoning and tool calls
for event in response.stream_events():
    if event.type == "reasoning":
        print(f"[thinking] {event.chunk}", end="", flush=True)
    elif event.type == "text":
        print(event.chunk, end="", flush=True)
    elif event.type == "tool_call_name":
        print(f"\n[calling tool: {event.chunk}]")
    elif event.type == "tool_call_args":
        print(event.chunk, end="", flush=True)
```

For async, the equivalents are `async for chunk in response` (text only) and `async for event in response.astream_events()` (everything).

### How Response assembles parts from events

Internally, Response consumes StreamEvents and builds up parts:

1. It maintains a `_current_part_index` and a buffer for the current part.
2. When an event arrives with a new `part_index`, the previous part is finalized and appended to `self._parts`.
3. Text and reasoning events accumulate string content.
4. `tool_call_name` events start a new ToolCallPart. `tool_call_args` events accumulate JSON string content. When the part finalizes, the accumulated JSON is parsed into a dict.
5. When streaming ends, the final part is finalized.

After streaming completes, `response.parts` is a clean `list[Part]` with the complete structured data.

### Handling server-side tool calls

For APIs like Claude where tool calls execute on the server and the full call/result sequence comes back in one response, the model plugin emits parts directly:

```
StreamEvent(type="text", chunk="Let me look that up", part_index=0)
# ...text chunks...
StreamEvent(type="tool_call_name", chunk="code_execution", part_index=1)
StreamEvent(type="tool_call_args", chunk='{"code": "print(1+1)"}', part_index=1)
# Part 1 finalizes as ToolCallPart(server_executed=True)
StreamEvent(type="tool_result", chunk='2', part_index=2)
# Part 2 finalizes as ToolResultPart(server_executed=True)
StreamEvent(type="text", chunk="The answer is 2", part_index=3)
```

These parts are stored just like any other parts, but `server_executed=True` marks them as not having been executed by LLM's tool framework.

A new `StreamEvent.type` value `"tool_result"` handles streaming server-side tool results. There may be additional event types needed for specific providers — the system is extensible.

## The `parts=[]` Prompt Parameter

### API

```python
response = model.prompt(parts=[
    TextPart(role="user", text="What's in this image?"),
    AttachmentPart(role="user", attachment=Attachment(path="photo.jpg")),
])
```

This replaces the need to construct multi-message prompts via Conversation when you already have the full history. It's the "power user" API — you're constructing exactly the messages you want sent to the model.

### How it interacts with existing parameters

`model.prompt(prompt="hello")` remains the simple path. Internally it constructs `parts=[TextPart(role="user", text="hello")]`. The existing `system=`, `fragments=`, `attachments=` parameters also work as before — they're assembled into parts before being passed to the model.

If both `prompt=` and `parts=` are provided, that's an error.

### How Conversation uses parts

Currently, Conversation holds a list of Response objects. When a model plugin needs the conversation history, it reads `conversation.responses` and reconstructs messages from prompt/response text.

With parts, each Response carries its own `parts` list. When the model plugin builds the API request, it walks `conversation.responses` and reads `response.prompt.parts` (what the user sent) and `response.parts` (what the model returned). This is a much more faithful representation than the current approach of just prompt text + response text.

Conversation itself stays as syntactic sugar — it's still a convenient way to do multi-turn exchanges. But the underlying data is now parts all the way down.

## Database Schema

### New table: `parts`

```sql
CREATE TABLE parts (
    id INTEGER PRIMARY KEY,
    response_id TEXT REFERENCES responses(id),
    role TEXT NOT NULL,          -- "user", "assistant", "system", "tool"
    part_type TEXT NOT NULL,     -- "text", "reasoning", "tool_call", "tool_result", "attachment"
    "order" INTEGER NOT NULL,
    content TEXT,                -- Text content for text/reasoning parts
    content_json TEXT,           -- JSON for structured data (tool call args, tool result details)
    tool_call_id TEXT,           -- Links tool calls to their results
    server_executed INTEGER,     -- 1 for server-side tool calls/results
    UNIQUE(response_id, "order")
);
```

The `content` column holds text for TextPart and ReasoningPart. The `content_json` column holds JSON for ToolCallPart (name, arguments), ToolResultPart (name, output, exception), and AttachmentPart (attachment metadata). This split avoids JSON-wrapping simple text.

### Migration strategy

- Add the `parts` table in a new migration (m022 or similar).
- Write a backfill migration that populates `parts` from existing data in `responses`, `tool_calls`, `tool_results`, etc. This runs once on upgrade.
- `log_to_db()` writes to the new `parts` table. Initially it also continues writing to the old tables for backward compatibility with external tools that query them directly.
- `from_row()` reads from the `parts` table. Falls back to old tables if `parts` is empty (for databases that haven't been backfilled).
- The old tables remain indefinitely. They can be deprecated and eventually dropped in a future major version.

### Fragment deduplication

The existing fragment deduplication (hash-based, content stored once) is valuable for system prompts that repeat across many responses. This can extend to parts: a `part_contents` table keyed by hash, with `parts.content_hash` referencing it. But this is an optimization to add later — start with inline content in the `parts` table and measure whether dedup matters.

## Serialization Without SQLite

```python
# Export a conversation to a dict
data = conversation.to_dict()
# {
#     "id": "01J...",
#     "model": "claude-4-sonnet",
#     "responses": [
#         {
#             "id": "01J...",
#             "input_parts": [
#                 {"role": "user", "type": "text", "text": "Hello"}
#             ],
#             "output_parts": [
#                 {"role": "assistant", "type": "text", "text": "Hi there!"}
#             ],
#             "usage": {"input": 10, "output": 25}
#         }
#     ]
# }

# Round-trip back
conversation = Conversation.from_dict(data, model=model)

# Save/load from JSON file
import json
Path("conversation.json").write_text(json.dumps(data))
```

This gives library users a way to persist and restore conversations without touching SQLite. The dict format matches the parts model 1:1.

## Implementation Sequence

### Phase 1: Part types and StreamEvent (no breaking changes)

1. Define the Part dataclass hierarchy and StreamEvent in a new `llm/parts.py` module.
2. Add `to_dict()` / `from_dict()` on all Part types. Write thorough tests.
3. Add `stream_events()` and `astream_events()` methods to Response/AsyncResponse. Initially they just wrap existing `str` chunks as `StreamEvent(type="text", ...)`.
4. Add `response.parts` property that materializes parts from the internal state after completion.
5. Export new types from `llm/__init__.py`.

At this point, everything works exactly as before. The new types exist but nothing requires them.

### Phase 2: Teach Response to handle StreamEvents from plugins

1. Update `Response.__iter__` to handle `str | StreamEvent` from `execute()`. Plain `str` yields are treated as text events (backward compat). StreamEvent yields are processed by the assembler.
2. The existing `__iter__` still only yields `str` (text chunks). The assembler runs as a side effect, populating `self._parts`.
3. `stream_events()` now yields real StreamEvents sourced from the assembler.
4. Same changes for AsyncResponse.

At this point, any plugin can start yielding StreamEvents and consumers will see them via `stream_events()`. But no plugin is required to change.

### Phase 3: Update built-in model plugins

1. Update the Anthropic plugin (llm-claude-3) to yield StreamEvents for reasoning tokens (extended thinking) and for server-side tool calls.
2. Update the OpenAI plugin (built-in) to yield StreamEvents for reasoning tokens from o-series models.
3. Update the Gemini plugin (llm-gemini) to yield StreamEvents as appropriate.

Each plugin update is independent and can be released separately.

### Phase 4: The `parts=[]` parameter

1. Add the `parts` parameter to `model.prompt()` and `model.chain()`.
2. Update Prompt to carry parts internally.
3. Update the model plugins to read `prompt.parts` when building API requests, falling back to the existing `prompt.prompt` / `prompt.system` / `prompt.attachments` for backward compat.
4. Update Conversation to use parts for history reconstruction.

### Phase 5: Database migration

1. Add the `parts` table migration.
2. Update `log_to_db()` to write parts.
3. Update `from_row()` to read parts.
4. Write the backfill migration for existing data.
5. Update the CLI display code to render parts appropriately (showing reasoning, server-side tool calls, etc.).

### Phase 6: Dict serialization

1. Add `conversation.to_dict()` and `Conversation.from_dict()`.
2. Add `response.to_dict()` and matching `from_dict()`.
3. These use the Part `to_dict()` / `from_dict()` methods from Phase 1.

## Open Questions

- **Should `parts=[]` and `prompt=` be mutually exclusive, or should `prompt=` just be sugar for a single TextPart?** The plan above says mutually exclusive, but there's an argument for letting them combine (prompt= adds a TextPart to the end of the parts list).
- **How should fragments interact with parts?** Fragments are currently prepended to the prompt text. In the parts world, they could become additional TextParts with role="user", or they could remain as a text-assembly mechanism that produces a single TextPart. The latter is simpler.
- **What event types do we actually need?** The plan lists text, reasoning, tool_call_name, tool_call_args, and tool_result. Specific providers may need more (e.g., Anthropic's "redacted_thinking" content blocks, Gemini's executable code blocks). Better to discover these during the Phase 3 plugin work than to over-design now.
- **Should parts store the full system prompt?** Currently the system prompt is on the Prompt object, not the Response. With parts, it could be stored as a Part with role="system" on the input side. This simplifies the model — everything is a part — but system prompts don't change turn-to-turn so it's somewhat redundant.
- **Naming: "parts" vs "blocks" vs "content_blocks"?** Anthropic uses "content blocks", OpenAI uses "content" as an array. "Parts" is the working name. Worth a final decision before the public API ships.

## Research Needed

As noted in the overview, the starting point is research. Before implementing, gather concrete API response examples from each provider showing:

1. Multi-turn conversations with tool calls and results
2. Streaming responses with reasoning/thinking tokens
3. Server-side tool execution (Claude code execution, Gemini code execution)
4. Streaming tool call arguments (partial JSON)
5. Mixed content responses (text + images in response)
6. How each provider represents redacted reasoning tokens

The `plans/parts/research/` directory has SDK source for several providers. These should be studied to understand the exact shapes of streaming chunks and completed messages for each provider, so the Part/StreamEvent types can faithfully represent all of them.
