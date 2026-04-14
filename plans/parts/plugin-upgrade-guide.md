# Plugin Upgrade Guide: StreamEvent and Messages

This guide explains how to upgrade an LLM model plugin so that its
`execute()` method yields `StreamEvent` objects and its request builder
consumes `prompt.messages`. This enables rich streaming (reasoning,
tool calls, server-side tools) and structured message history.

## Backward compatibility

A plugin that still yields plain `str` from `execute()` continues to
work — the framework treats each string as an equivalent of
`StreamEvent(type="text", chunk=..., part_index=0)`. Upgrading is
opt-in.

## Step 0: Set up editable LLM dependency

Add LLM as an editable source in `pyproject.toml` so the plugin picks
up the matching core:

```toml
[tool.uv]
package = true

[tool.uv.sources]
llm = { path = "/path/to/llm", editable = true }
```

Then `uv sync --group dev` and run the existing tests with `uv run
pytest` to confirm nothing regresses before you start.

## Step 1: Import StreamEvent

```python
from llm.parts import StreamEvent
```

## Step 2: Yield StreamEvent from the streaming path

Find each `yield some_string` in the streaming code path and replace
it with a typed `StreamEvent`.

### Text chunks

```python
yield StreamEvent(type="text", chunk=content, part_index=0)
```

Skip empty text chunks. Many streaming APIs emit a final delta with
`"content": ""`; yielding those as StreamEvents adds noise.

`part_index` is a monotonically allocated counter that identifies
which part the chunk contributes to. See
[Allocating part_index](#allocating-part-index) below.

### Reasoning / thinking text

If the model streams reasoning as separate chunks:

```python
yield StreamEvent(type="reasoning", chunk=thinking_text, part_index=0)
```

If the model reports only a reasoning **token count** (opaque
reasoning, e.g. OpenAI GPT-5 series), record it on the response after
streaming ends:

```python
if reasoning_tokens > 0:
    response._reasoning_token_count = reasoning_tokens
```

The assembler automatically prepends a `ReasoningPart(redacted=True,
token_count=N)` to the output parts. Extract this value **before**
`set_usage()` — `set_usage()` may mutate the usage dict.

### Tool calls

When the model opens a new tool call:

```python
yield StreamEvent(
    type="tool_call_name",
    chunk=tool_name,
    part_index=tc_index,
    tool_call_id=tool_call_id,
)
```

Streaming tool call arguments use the same `part_index` as the name
event:

```python
yield StreamEvent(
    type="tool_call_args",
    chunk=partial_json_args,
    part_index=tc_index,
    tool_call_id=tool_call_id,
)
```

Also call `response.add_tool_call()` for each completed tool call. The
chain mechanism (`execute_tool_calls()`) reads from
`response.tool_calls()` which is populated by `add_tool_call()` — it
does not mine StreamEvents. For streaming, accumulate the tool call
arguments during the loop and call `response.add_tool_call()` once the
stream ends. For non-streaming, call it inline.

### Server-side tool results

For tools the API executes server-side (web search, code execution):

```python
yield StreamEvent(
    type="tool_result",
    chunk=result_text,
    part_index=tr_index,
    tool_call_id=associated_tool_call_id,
    server_executed=True,
    tool_name="web_search",
)
```

### Allocating `part_index`

`part_index` identifies a single logical part inside the response. The
assembler groups all events that share a `part_index` into one Part.
The rules the assembler enforces:

- Events with the same `part_index` must belong to the same content
  family. Mixing `text` and `tool_call_*` at the same index raises —
  allocate a new `part_index`.
- `tool_call_name` and `tool_call_args` at the same `part_index`
  combine into one `ToolCallPart` (the args stream onto the named
  tool call).

A typical allocator gives each distinct content block its own index:

```
part_index=0: reasoning chunks
part_index=1: text chunks
part_index=2: first tool_call (name + args)
part_index=3: second tool_call if parallel
```

For simple text-only responses, `part_index=0` for every text event
is fine.

### Multiple messages in one response

Server-side tool execution can produce a response that spans more than
one assistant turn (e.g. reasoning → tool call → tool result →
follow-up text, sometimes split into separate messages by the
provider). `StreamEvent` has a `message_index` field (default `0`) for
this case. Plugins that do not emit multiple messages can leave it at
`0` and ignore it — one response becomes one assistant Message.

## Step 3: Yield StreamEvent from the non-streaming path

Convert the single `yield response_text` in the non-streaming branch
to one `StreamEvent` per content block:

```python
yield StreamEvent(type="reasoning", chunk=thinking_text, part_index=0)
yield StreamEvent(type="text", chunk=response_text, part_index=1)
```

Simple text-only non-streaming:

```python
yield StreamEvent(type="text", chunk=response_text, part_index=0)
```

## Step 4: Update async execute()

The async `execute()` follows the same pattern. Note: inside an `async
def` generator you cannot `yield from` a synchronous helper generator;
loop explicitly:

```python
for ev in self._emit_tool_call_events(delta, ...):
    yield ev
```

## Step 5: Consume prompt.messages in build_messages

`prompt.messages` is the canonical structured input — a list of
`llm.Message` objects, each with a `role` and a list of parts
(`TextPart`, `AttachmentPart`, `ToolCallPart`, `ToolResultPart`,
`ReasoningPart`). Iterate these and translate to whatever the API
expects:

```python
for message in prompt.messages:
    for part in message.parts:
        if isinstance(part, TextPart):
            ...
        elif isinstance(part, AttachmentPart):
            ...
        elif isinstance(part, ToolCallPart):
            ...
        elif isinstance(part, ToolResultPart):
            ...
```

For conversation history, walk `conversation.responses` and consume
`prev_response.prompt.messages` (previous input) followed by either
`prev_response.messages` (the structured assistant response) or the
flat accessors `prev_response.text_or_raise()` and
`prev_response.tool_calls_or_raise()` for simple text-plus-tool-calls
turns.

The simple single-string API (`model.prompt("hi", system="...")`)
keeps working because the framework synthesizes `prompt.messages` from
`prompt=`, `system=`, `attachments=`, and `tool_results=`
automatically.

## Step 6: Opaque provider metadata

Providers attach opaque data that clients must echo back on the next
request (Anthropic `signature` on thinking blocks, Gemini
`thoughtSignature` on function calls, Anthropic `encrypted_content`
inside server-side tool results, OpenAI Responses `encrypted_content`
on reasoning items). Stash these on the relevant `StreamEvent` via
`provider_metadata`, namespaced by provider:

```python
yield StreamEvent(
    type="reasoning",
    chunk="",
    part_index=0,
    provider_metadata={"anthropic": {"signature": sig}},
)
```

The framework merges per-event `provider_metadata` onto the finalized
Part (last non-None value wins per top-level key) and persists it.
When you later consume `prompt.messages` during history reconstruction,
read `part.provider_metadata["<your-namespace>"]` and fold those
opaque fields back into the outgoing request.

Treat other providers' entries as opaque; don't parse them.

See the [Preserving opaque provider metadata section in the plugin
docs](../../docs/plugins/advanced-model-plugins.md) for details and
examples.

## Step 7: Tests

Verify:

1. **`stream_events()` yields the expected event types.** Call
   `response.stream_events()` (sync) or `response.astream_events()`
   (async) and check each yielded event.
2. **`response.messages` assembles correctly.** After
   `response.text()`, assert the structure of `response.messages` —
   typically one assistant `Message` whose parts include the expected
   `TextPart` / `ReasoningPart` / `ToolCallPart` objects.
3. **Backward compat.** `list(response)` still yields strings;
   `response.text()` still returns the full text.

```python
from llm.parts import StreamEvent, TextPart

@pytest.mark.vcr
def test_stream_events():
    model = llm.get_model("your-model-id")
    response = model.prompt("Say hello", key=API_KEY)
    events = list(response.stream_events())
    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) > 0
    msgs = response.messages
    assert msgs[0].role == "assistant"
    assert isinstance(msgs[0].parts[0], TextPart)
```

Record cassettes:

```bash
rm tests/cassettes/test_yourplugin/test_stream_events.yaml
YOUR_API_KEY="$(llm keys get yourkey)" \
  uv run pytest -k test_stream_events --record-mode once --inline-snapshot=fix
```

## Step 8: Manual CLI test

```bash
LLM_USER_PATH=/tmp/test-user-path YOUR_API_KEY="$(llm keys get yourkey)" \
  uv run llm -m your-model "Say hello"
```

Text should appear on stdout. If the model supports reasoning:

```bash
uv run llm -m your-model -o thinking true "Two pet names"
```

Reasoning text is rendered on stderr in a dim style; the final
response on stdout.

## Plugins that inherit from built-in OpenAI models

If your plugin subclasses or reuses the built-in OpenAI `Chat` /
`AsyncChat` (OpenRouter, local OpenAI-compatible endpoints, etc.), you
inherit StreamEvent emission and messages-based request construction
for free. The upgrade work is limited to:

1. Adding the editable LLM source to `pyproject.toml`.
2. Running existing tests.
3. Adding StreamEvent-specific tests.
4. Re-recording VCR cassettes if the request body shape changed.

## Storage: the DAG message store (transparent to plugins)

Starting with the DAG schema work (see `plans/dag-schema.md`), `llm`
stores messages as an immutable, parent-linked, content-addressed DAG
instead of per-response rows.

**Plugins do not need to do anything.** `execute()` still yields
`StreamEvent`s; request builders still consume
`prompt.messages: list[Message]`. `Message`, `Part`, and
`provider_metadata` are unchanged. The storage layer (`llm.storage.MessageStore`)
hashes and persists messages behind the scenes.

Two things to be aware of:

- **`provider_metadata` is part of message identity.** Opaque fields
  like Anthropic `signature`, OpenAI `encrypted_content`, Gemini
  `thoughtSignature` go into the content hash. A plugin that echoes
  these verbatim (as it must, for continuation) will dedup cleanly.
  A plugin that drops or normalizes them will cause silent chain
  forking — don't.
- **Floats are forbidden in `provider_metadata`.** Representation drift
  would break hashes. Use ints or strings instead. The canonicalizer
  raises `TypeError` at save time if it encounters one.

## Checklist

- [ ] `pyproject.toml`: editable `llm` source added
- [ ] `from llm.parts import StreamEvent` added to plugin
- [ ] Streaming `execute()` yields `StreamEvent` (not `str`)
- [ ] Non-streaming `execute()` yields `StreamEvent` (not `str`)
- [ ] Async `execute()` updated the same way
- [ ] Reasoning handled (streamed OR `response._reasoning_token_count`)
- [ ] Tool calls emit `tool_call_name` + `tool_call_args` AND call
      `response.add_tool_call()`
- [ ] Server-side tools (if applicable) emit events with
      `server_executed=True`
- [ ] `build_messages` consumes `prompt.messages` (not legacy fields)
- [ ] Conversation history reads `prev_response.prompt.messages` and
      either `prev_response.messages` or `text_or_raise()` /
      `tool_calls_or_raise()`
- [ ] `provider_metadata` round-trips for opaque provider fields
      (signatures, encrypted blobs)
- [ ] Tests: `stream_events()` yields the expected events
- [ ] Tests: `response.messages` assembles correctly
- [ ] Tests: backward compat (`list(response)` yields `str`)
- [ ] VCR cassettes recorded
- [ ] Manual CLI test passes
