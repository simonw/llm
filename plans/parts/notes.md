# Parts Implementation Notes

Notes from implementing Phase 1 and Phase 2 (2026-04-04).

## Design decisions made during implementation

### `_process_chunk()` as shared method on `_BaseResponse`

Both sync and async Response need the same logic for handling `str | StreamEvent` from `execute()`. Rather than duplicating, I put `_process_chunk()` and `_build_parts()` on `_BaseResponse`. `_process_chunk` returns the text `str` to yield (or `None` to filter), and as a side effect populates both `_chunks` and `_stream_events`.

### `stream_events()` is a separate code path from `__iter__`

`stream_events()` on Response runs its own iteration of `execute()` (it doesn't delegate to `__iter__`). This is because `__iter__` filters non-text events, but `stream_events()` needs to yield everything. They share `_process_chunk()` logic but manage the generator independently. **This means you can call either `__iter__` OR `stream_events()` on a response, but not both during live streaming** — the first one to run consumes the generator.

After completion, both work fine: `__iter__` replays `_chunks`, `stream_events()` replays `_stream_events` (or synthesizes from text if no events were recorded).

### Parts property is synchronous even on AsyncResponse

`response.parts` is a `@property` (not async) on both Response and AsyncResponse. On AsyncResponse, it raises `ValueError` if not yet awaited. This keeps the API simple — you `await` the response first, then inspect `.parts`. The alternative (an async method) would make the common case of "get response, then look at parts" more verbose.

## Live testing observations (gpt-5.4-mini)

- **OpenAI streams an empty first chunk**: The first chunk from the streaming API is `""` (empty string). This is the chunk that carries the `role: "assistant"` delta. Our assembler handles this fine — it just becomes an empty text event.

- **Chunk count varies**: "Count from 1 to 5" produced 10 chunks for "1 2 3 4 5" — roughly one token per chunk, including spaces as separate tokens.

- **Usage data still works**: `response.usage()` returns `Usage(input=10, output=4)` for simple prompts. The `details` field is an empty dict `{}` for gpt-5.4-mini (no breakdown like reasoning tokens).

- **Current OpenAI plugin yields only `str`**: Since we haven't updated the OpenAI plugin to emit `StreamEvent` objects yet (that's Phase 3), all chunks come through as plain strings. The backward compat path (`_has_stream_events = False`) handles this correctly. Parts are synthesized as a single `TextPart` by `_build_parts()`.

## Things to watch for in Phase 3

- **Empty chunks from OpenAI**: When updating the OpenAI plugin to emit StreamEvents, need to handle the empty first chunk. Could either skip it or let it through (it's harmless).

- **Tool call streaming**: OpenAI streams tool call arguments as incremental JSON string fragments. The `tool_call_args` event type with accumulating chunks and JSON parse on finalize should handle this, but needs testing with actual tool calls.

- **Reasoning tokens**: OpenAI's o-series models don't expose reasoning text (just token counts). Will need to emit `ReasoningPart(redacted=True, token_count=N)` — this is data from the usage response, not from streaming chunks.

- **`stream_events()` vs `__iter__` mutual exclusion**: Currently if you call `stream_events()` the response gets consumed there. If someone then tries to iterate with `for chunk in response`, it'll see `_done=True` and replay `_chunks`. This works but is subtle. May want to document this.

## Phase 3 observations

### OpenAI plugin
- **set_usage mutates the dict**: `set_usage()` calls `pop()` which destroys `completion_tokens_details`. Must extract `reasoning_tokens` BEFORE calling `set_usage()`.
- **Reasoning tokens are opaque**: gpt-5.4-mini reports `reasoning_tokens` in usage but never streams reasoning content. Only appears with `reasoning_effort='high'` or harder problems.
- **Tool call part_index tracking**: When OpenAI streams tool calls after text, need to track whether text was emitted to assign correct part indices.

### Anthropic plugin (llm-anthropic)
- **Thinking tokens are streamed**: Unlike OpenAI/Gemini, Anthropic streams actual thinking text as `thinking_delta` events. This gives us real `ReasoningPart(text=...)` content, not redacted.
- **Server-side tools have distinct types**: `server_tool_use` vs regular `tool_use` in content block types. `web_search_tool_result` is a separate block type with nested content.
- **Web search results only in final message**: The `web_search_tool_result` blocks aren't streamed — they appear in the final message. We extract them post-stream.
- **Schema streaming uses partial_json**: When a schema is set, Anthropic sends `partial_json` deltas instead of text deltas. Currently we treat these as text events (they build up JSON that gets parsed by the schema handler).

### Gemini plugin (llm-gemini)
- **Thinking tokens are opaque**: Like OpenAI, Gemini reports `thoughtsTokenCount` in usage but doesn't stream thinking text. Uses `_reasoning_token_count` pattern.
- **Complete parts per chunk**: Gemini doesn't stream partial tool arguments — each chunk contains complete parts. This simplifies the tool call event emission.
- **Code execution as server-side tool**: `executableCode` and `codeExecutionResult` parts become `tool_result` StreamEvents with `server_executed=True`.
- **Thought signatures**: Gemini 3 models include `thoughtSignature` on tool call parts, required for round-tripping. Stored as attribute on ToolCall object.

### StreamEvent additions
- Added `server_executed` and `tool_name` fields to StreamEvent dataclass for plugins with server-side tool execution.

## Implementation stats

- Phase 1 + 2: ~300 lines of new code in `llm/parts.py` and `llm/models.py`
- Phase 3: ~500 lines changed across 3 plugins (OpenAI, Anthropic, Gemini)
- 41 unit tests in llm core, 513 total tests passing
- llm-anthropic: 22 tests passing (4 new)
- llm-gemini: 37 tests passing (3 new)
- Live tested against gpt-5.4-mini, claude-haiku-4.5, gemini-3-flash-preview

## Phase 4 observations

- `prompt=` is sugar for `TextPart(role="user", text=...)` in `input_parts`
- `system=` becomes `TextPart(role="system", text=...)` in `input_parts`
- `parts=` and `prompt=` combine (parts first, then system, then prompt, then attachments)
- Existing model plugins still read `prompt.prompt` and `prompt.system` — they don't read `input_parts` yet. Plugin migration to read from `input_parts` is a future step.
- `input_parts` is computed on-demand (property), not stored on the Prompt

## Phase 5 observations

- Parts table uses `direction` column ("input"/"output") to distinguish prompt vs response parts
- Both input parts and output parts stored in the same table with a unique index on `(response_id, direction, order)`
- `from_row()` only loads output parts into `_loaded_parts` — input parts are still reconstructed from the existing prompt/system/attachments columns
- The `parts` property checks for `_loaded_parts` first (from DB), then falls back to `_build_parts()` (from stream events)
- Old databases without the parts table still work — `log_to_db` checks for table existence before writing

## Final stats

- 524 total tests in llm core, all passing
- 22 tests in llm-anthropic, all passing  
- 37 tests in llm-gemini, all passing
- 12 commits across all repos
