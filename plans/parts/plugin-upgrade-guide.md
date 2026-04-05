# Plugin Upgrade Guide: StreamEvent / Parts Support

This guide explains how to upgrade an LLM model plugin to emit `StreamEvent` objects from its `execute()` method, enabling rich streaming (reasoning tokens, tool calls, server-side tools) and structured parts.

## Background

Previously, `execute()` yielded plain `str` chunks. The new system introduces `StreamEvent` — a typed wrapper that tells the framework what kind of content each chunk represents: text, reasoning, tool call name/args, or tool result.

**Backward compatibility is preserved.** Plugins that still yield `str` will continue to work — the framework treats bare strings as `StreamEvent(type="text", ...)` automatically. This upgrade is opt-in.

## Step 0: Set up editable LLM dependency

Add the editable LLM source to `pyproject.toml` so the plugin uses the parts-branch LLM:

```toml
[tool.uv]
package = true

[tool.uv.sources]
llm = { path = "/path/to/llm", editable = true }
```

Then sync: `uv sync --group dev`

Run existing tests to confirm nothing is broken: `uv run pytest`

## Step 1: Import StreamEvent

At the top of your plugin file:

```python
from llm.parts import StreamEvent
```

## Step 2: Update execute() — streaming path

Find every `yield some_string` in the streaming code path and replace it with a `yield StreamEvent(...)`.

### Text chunks

Before:
```python
yield content
```

After:
```python
yield StreamEvent(type="text", chunk=content, part_index=part_index)
```

**Filter empty chunks:** Many APIs send empty string content in their final delta (e.g., `"content": ""`). Skip these — only yield a text StreamEvent when the content is non-empty. The old pattern of yielding bare empty strings was harmless but with StreamEvents it creates unnecessary noise.

`part_index` is a counter that increments each time the model starts a new logical part (e.g., switches from reasoning to text, or from text to a tool call). For simple text-only responses, `part_index=0` for all chunks is fine.

### Reasoning / thinking tokens

If the model streams reasoning/thinking content as separate chunks:

```python
yield StreamEvent(type="reasoning", chunk=thinking_text, part_index=part_index)
```

If the model only reports reasoning token **counts** in usage (opaque reasoning, like OpenAI), store the count on the response object after streaming ends:

```python
if reasoning_tokens > 0:
    response._reasoning_token_count = reasoning_tokens
```

The framework's `_build_parts()` will automatically prepend a `ReasoningPart(redacted=True, token_count=N)`.

**Important:** Extract reasoning token counts from usage data **before** calling `set_usage()`, because `set_usage()` may mutate the usage dict.

### Tool calls

When the model starts a new tool call:

```python
yield StreamEvent(
    type="tool_call_name",
    chunk=tool_name,
    part_index=part_index,
    tool_call_id=tool_call_id,
)
```

For streaming tool call arguments:

```python
yield StreamEvent(
    type="tool_call_args",
    chunk=partial_json_args,
    part_index=part_index,  # same part_index as the tool_call_name
    tool_call_id=tool_call_id,
)
```

**Important:** You must **also** call `response.add_tool_call()` for each tool call, in addition to yielding the StreamEvent objects. The chain mechanism (`execute_tool_calls()`) reads from `response.tool_calls()` which uses the `_tool_calls` list populated by `add_tool_call()` — it does not automatically extract tool calls from stream events. For streaming, accumulate tool call data during the loop and call `response.add_tool_call()` after the loop finishes. For non-streaming, call it inline.

### Server-side tool results

For tools the API executes server-side (web search, code execution):

```python
yield StreamEvent(
    type="tool_result",
    chunk=result_text,
    part_index=part_index,
    tool_call_id=associated_tool_call_id,
    server_executed=True,
    tool_name="web_search",
)
```

Set `server_executed=True` on the `StreamEvent` so the assembled `ToolCallPart`/`ToolResultPart` is marked accordingly.

### Part index tracking

`part_index` should increment when the model transitions between different content types. A typical sequence:

```
part_index=0: reasoning chunks
part_index=1: text chunks  
part_index=2: tool_call_name + tool_call_args
part_index=3: another tool_call (if parallel)
```

For simple text-only responses, all events can use `part_index=0`.

## Step 3: Update execute() — non-streaming path

The non-streaming path typically yields a single string. Convert it to yield `StreamEvent` objects for each content block in the response. For example, if the response has thinking + text:

```python
yield StreamEvent(type="reasoning", chunk=thinking_text, part_index=0)
yield StreamEvent(type="text", chunk=response_text, part_index=1)
```

For simple text-only non-streaming:

```python
yield StreamEvent(type="text", chunk=response_text, part_index=0)
```

## Step 4: Update async execute()

Apply the same changes to the async `execute()` method. The pattern is identical — `yield StreamEvent(...)` instead of `yield str`.

**Note:** In an `async def execute()` generator, you cannot use `yield from` on a synchronous generator. If you have a helper method that yields StreamEvents (e.g., for tool call processing), use an explicit loop:

```python
for ev in self._emit_tool_call_events(delta, ...):
    yield ev
```

## Step 5: Add tests

Add tests that verify:

1. **`stream_events()` yields correct event types:** Call `response.stream_events()` (sync) or `response.astream_events()` (async) and check that you get the expected event types (text, reasoning, tool_call_name, etc.).

2. **`response.parts` assembles correctly:** After `response.text()`, check that `response.parts` contains the right `TextPart`, `ReasoningPart`, `ToolCallPart` objects.

3. **Backward compat:** `list(response)` still yields plain strings, `response.text()` still works.

Example test:

```python
from llm.parts import StreamEvent, TextPart

@pytest.mark.vcr
def test_stream_events():
    model = llm.get_model("your-model-id")
    response = model.prompt("Say hello", key=API_KEY)
    events = list(response.stream_events())
    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) > 0
    parts = response.parts
    assert len(parts) >= 1
    assert isinstance(parts[0], TextPart)
```

Record VCR cassettes for the new tests. If using inline-snapshot:

```bash
rm tests/cassettes/test_yourplugin/test_stream_events.yaml
YOUR_API_KEY="$(llm keys get yourkey)" uv run pytest -k test_stream_events --record-mode once --inline-snapshot=fix
```

## Step 6: Manual CLI test

```bash
LLM_USER_PATH=/tmp/test-user-path YOUR_API_KEY="$(llm keys get yourkey)" \
  uv run llm -m your-model "Say hello"
```

Verify text output appears on stdout. If the model supports reasoning:

```bash
uv run llm -m your-model -o thinking true "Two pet names"
```

Reasoning should appear on stderr in dim text, response on stdout.

## Plugins that inherit from built-in models

If your plugin subclasses or reuses the built-in OpenAI `Chat`/`AsyncChat` classes (e.g., OpenRouter, local OpenAI-compatible APIs), your plugin may already get StreamEvent support for free — the parent class `execute()` was updated in Phase 3.

In this case, the upgrade is:
1. Set up editable LLM dependency
2. Run existing tests — they should pass
3. Add StreamEvent-specific tests to verify the behavior
4. Re-record VCR cassettes if needed

## Checklist

- [ ] `pyproject.toml`: editable llm source added
- [ ] `from llm.parts import StreamEvent` added to plugin
- [ ] Streaming `execute()`: yields `StreamEvent` instead of `str`
- [ ] Non-streaming `execute()`: yields `StreamEvent` instead of `str`
- [ ] Async `execute()`: same changes
- [ ] Reasoning tokens handled (streamed or opaque via `_reasoning_token_count`)
- [ ] Tool calls emit `tool_call_name` and `tool_call_args` events
- [ ] Server-side tools (if applicable) emit events with `server_executed=True`
- [ ] Tests: `stream_events()` yields correct events
- [ ] Tests: `response.parts` assembles correctly
- [ ] Tests: backward compat (`list(response)` yields `str`)
- [ ] VCR cassettes recorded for new tests
- [ ] Manual CLI test passes
