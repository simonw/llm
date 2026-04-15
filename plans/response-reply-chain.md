# Ergonomic chain APIs: `reply()`, `fork()`, `model.chain()`

Status: design proposal.

## Motivation

The DAG work in `plans/dag-schema.md` made every message identifiable
and every chain reconstructible from any node. That opens up
ergonomic surface that was awkward before:

- Continuing a conversation without manually instantiating a
  `Conversation`.
- Branching at any response without rebuilding message history.
- Running a tool-resolving loop (chain) without a Conversation wrapper.
- Changing the available tool set turn-by-turn.

Today's Python API funnels all of this through `Conversation`:

```python
conv = model.conversation(tools=[search])
r1 = conv.prompt("plan a trip")
r2 = conv.prompt("add a day")  # implicitly continues
r_chain = conv.chain("resolve this", tools=[search, cal])
```

That works but is heavier than it needs to be for the common cases.
With the DAG as ground truth, `Conversation` becomes "a named bookmark
into the DAG" — useful but no longer mandatory.

## Goals

1. Add `response.reply(prompt, ...)` for multi-turn continuation.
2. Add `response.fork(prompt=None, ...)` for branching.
3. Add `model.chain(prompt, *, tools=, ...)` as a sibling to
   `model.prompt()` for single-invocation tool loops without a
   Conversation.
4. Make turn-by-turn tool-set changes safe and auditable.
5. Keep `Conversation` as-is. Nothing deprecated.

## Non-goals

- Removing or hiding `Conversation`. It remains the right shape for
  named, hook-configured, persistent threads.
- Changing `model.prompt()`'s single-call semantics. Auto tool
  resolution stays opt-in via `model.chain()`.
- Rebuilding provider-adapter history reconstruction to walk the DAG
  directly (that's in `plans/dag-schema.md`'s Deferred list).

## Design

### `Response.reply(prompt=None, *, messages=None, tools=None, **kwargs) -> Response`

Continue the conversation this response belongs to with a new turn.

```python
def reply(self, prompt=None, *, messages=None, tools=None, **kwargs):
    conv = self.conversation or self.model.conversation()
    if not conv.responses or conv.responses[-1] is not self:
        conv.responses.append(self)
    return conv.prompt(
        prompt,
        messages=messages,
        tools=tools if tools is not None else conv.tools,
        **kwargs,
    )
```

- If the response already has a `conversation`, reuse it — that
  preserves hooks, tools, chain_limit, persistence.
- If not, create an ad-hoc Conversation with the same model and append
  `self` so history reconstruction works.
- `tools=` defaults to inheriting from the Conversation; pass `[]` to
  drop tools for this turn, pass a list to override.

The **async** counterpart is `AsyncResponse.reply()` with the same
signature, returning `AsyncResponse`.

### `Response.fork(prompt=None, *, name=None, model=None, **kwargs) -> Response`

Branch at this response. Returns a new Response whose conversation is
a *new* row pointing at this response's head message — shared prefix,
independent future.

```python
def fork(self, prompt=None, *, name=None, model=None, **kwargs):
    from .storage import MessageStore
    # Ensure this response has been persisted — we need its head id.
    head_id = self.head_output_message_id_or_raise()
    db = self._db_or_raise()
    new_conv_id = MessageStore(db).fork(
        head_id, name=name, model=model or self.model.model_id
    )
    new_conv = load_conversation(new_conv_id, database=db.path)
    if prompt is None and kwargs.get("messages") is None:
        # Return the empty new conversation's "entry point" — callers
        # can `.prompt()` on the returned Conversation instead.
        return new_conv
    return new_conv.prompt(prompt, **kwargs)
```

Two valid call shapes:

```python
# Branch + prompt in one step
r2 = r1.fork("retry with a different angle")

# Branch, then drive the new conversation yourself
new_conv = r1.fork()
r2 = new_conv.prompt("...", tools=[different_tools])
```

Returns `Response` if prompted, `Conversation` if not — the sole
polymorphic case; alternative is two methods (`fork()` always returns
Conversation; `fork_and_prompt()` returns Response) but the
overloading reads better in practice.

Async counterpart: `AsyncResponse.fork()`.

### `Model.chain(prompt, *, tools=, chain_limit=, before_call=, after_call=, **kwargs) -> ChainResponse`

Single-invocation tool loop without a Conversation.

```python
def chain(self, prompt=None, *, tools=None, chain_limit=None,
          before_call=None, after_call=None, **kwargs):
    conv = self.conversation(tools=tools, chain_limit=chain_limit)
    return conv.chain(
        prompt,
        before_call=before_call,
        after_call=after_call,
        **kwargs,
    )
```

Mirrors `Conversation.chain()`'s signature. Behaviorally identical;
the difference is that you don't need to instantiate a Conversation
first.

`AsyncModel.chain()` is the async twin.

### Dynamic tool-set handling

Tool availability is per-call, not per-conversation, *today* — but the
ergonomics have footguns worth fixing.

1. **Per-call `tools=` override is already correct.** `reply()`,
   `fork()`, `chain()`, and `Conversation.prompt/chain()` all accept
   `tools=`. Passing `tools=[]` drops tools for one turn; passing a
   list overrides.

2. **Store the tool set on each call.** Today the `tool_responses`
   table links tools to response_ids. Mirror that into `calls` so an
   auditor can ask "what tools did the model have when it made this
   call?" without joining through `responses`. Cheapest option: a
   `calls_tools(call_id, tool_id)` join table, populated by
   `_log_messages_to_db`.

3. **Schema-drift warning.** When a call's tool list contains a tool
   *name* that appeared earlier in the chain under a *different
   schema* (different `input_schema` hash), log a warning. Cheap
   heuristic against the silent-breakage case where a user renames a
   field in a tool between turns.

4. **Expose `response.tools`** as a property that returns the
   `Tool`-like objects available for this specific call (read via the
   `calls_tools` join). Useful for introspection and for UIs that
   want to render "what could the model have done here?".

### Async variants

Every sync method above has an async twin with identical signature,
returning `AsyncResponse` / `AsyncConversation` / `ChainResponse`'s
async form. No design differences.

## Behavior specification

### `reply()` when `self` hasn't been logged yet

Valid. The conversation's history comes from its responses list in
memory, not from the DB. The follow-up call runs with the right
context; when it's eventually logged, the whole chain (including
self) lands in the DAG, dedup-preserving the shared prefix.

### `reply()` when the model is different

`reply()` uses `self.model` by default. Allow override:

```python
r2 = r1.reply("continue in Claude", model=claude)
```

`self.conversation.model` is set at Conversation construction; the
override applies only to this turn. This is already how
`Conversation.prompt(model=...)` works — no new machinery needed.

### `fork()` on an unlogged response

Rejected — `fork()` needs a persisted `head_output_message_id`. Raise
a clear ValueError with a hint: "call `response.text()` and
`response.log_to_db()` first, or use `reply()` to extend in-place
without branching."

### `model.chain()` without tools

Allowed. Degenerates to `model.prompt()` plus a single-iteration
ChainResponse wrapper. No behavior change, just return-type
consistency for code that sometimes has tools and sometimes doesn't.

### Persistence ergonomics

`reply()` / `fork()` / `chain()` currently persist only if the caller
calls `.log_to_db(db)` on the returned response. That matches the
rest of the API — no surprise DB writes.

A follow-up could add an implicit `auto_log` mode where the
model-scoped default database is written to automatically. Out of
scope here.

## Edge cases and footguns

- **`reply()` loops.** Nothing prevents `while True: r = r.reply(...)`.
  That's user code. No guard needed; chain_limit exists on
  Conversation for the bounded case.

- **`fork()` from a response whose conversation has hooks.** Hooks do
  *not* transfer — a fork is a new Conversation with default config.
  Rationale: hooks often close over per-thread state that isn't
  meaningful on a new branch. Document this.

- **Tool set drift across `reply()` calls.** Covered by the
  schema-drift warning.

- **Model drift across turns.** Already supported (Conversation +
  per-call `model=`). Document that `reply(model=...)` works and is
  the right path.

- **`response.reply()` on a ChainResponse.** ChainResponse wraps the
  final response in a chain; its `reply()` extends from there. Should
  just work — but add a test.

## Tests

Per-method, minimum:

- `reply()` extends the chain; DAG shows a parent_id chain through
  `self`'s head.
- `reply(tools=...)` overrides conversation tools for that turn only.
- `reply(model=...)` routes to the specified model but preserves
  conversation history.
- `reply()` on a Response without a conversation creates an ad-hoc one
  and works.
- `fork()` creates a new conversation row pointing at the right head.
- `fork(prompt=...)` returns a Response in the new conversation.
- `fork()` on an unlogged response raises.
- `model.chain()` resolves tools and returns ChainResponse.
- `model.chain(tools=[])` is equivalent to a single-call `prompt()`.
- Dynamic tool-set: call 1 with `[a, b]`, call 2 with `[b, c]` — both
  succeed; chain walk preserves the tool_call/tool_result pairs from
  call 1 even though `a` is no longer available.
- Schema-drift warning: two calls naming the same tool with different
  input schemas emits a warning.
- Async counterparts of each.

## Documentation

- `docs/python-api.md`: new section "Continuing and branching" showing
  `reply()`, `fork()`, `model.chain()` side-by-side with
  `Conversation`. Present them as equal-weight options; `Conversation`
  for named threads, the new methods for ad-hoc flows.
- `docs/plugins/advanced-model-plugins.md`: no changes needed;
  plugins don't see these methods.
- `plans/parts/plugin-upgrade-guide.md`: add a note that plugins
  receive the same `prompt.messages` regardless of which entry point
  was used.

## Implementation sequence

Each step lands as a separate commit with tests + docs:

1. **`model.chain()` sync + async.** Mechanically a thin wrapper over
   `Conversation.chain()`. Enables the tool-without-Conversation
   story. ~small.

2. **`response.reply()` sync + async.** Thin wrapper over
   `Conversation.prompt()`. ~small.

3. **`response.fork()` sync + async.** Wraps `MessageStore.fork()`
   plus optional immediate prompt. Needs the "rejected on unlogged
   response" path. ~medium.

4. **Per-call tool-set persistence.** New `calls_tools` join table in
   a follow-up migration (not m023-in-place; this is genuinely new
   schema). Wire `_log_messages_to_db` to write it. `response.tools`
   property reads it. ~medium.

5. **Schema-drift warning.** Compute `tool.hash()` for each tool per
   call; when a chain's prior turn had the same tool *name* under a
   different hash, log a warning. ~small.

6. **Docs + python-api page.** ~small.

## Open questions

1. **Should `fork()` transfer hooks?** Argued above that it shouldn't.
   A `keep_hooks=True` flag could be added later if demand emerges.

2. **Should `reply()` on a ChainResponse reply from the whole chain's
   final state, or from some specific inner response?** Whole-chain
   final state is the obvious default. A `reply_at(inner_response,
   ...)` method could be added if users want mid-chain branching —
   functionally equivalent to `inner_response.fork(...)`.

3. **Is a `model.fork(conversation_id, prompt)` shortcut worth it?**
   Today you'd do `load_conversation(id).responses[-1].fork(prompt)`.
   Probably not — too niche.

4. **Should `calls_tools` store the tool's *hash* rather than a
   foreign key?** Hash-keyed is more robust against tool renames and
   matches `fragments` / `tools` conventions elsewhere. Probably yes.

5. **Naming: `model.chain()` vs `model.resolve()` vs
   `model.agentic()`?** `chain()` mirrors the existing
   `Conversation.chain()` and is the least surprising. Stick with it.
