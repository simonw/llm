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

## Implementation stats

- Phase 1 + 2: ~300 lines of new code in `llm/parts.py` and `llm/models.py`
- 36 unit tests, all passing
- 508 total tests (including existing), zero regressions
- 6 live tests against gpt-5.4-mini, all passing
