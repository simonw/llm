# DAG-shaped message storage for LLM

Status: design proposal.

## Motivation

Today (parts branch), the `messages` and `message_parts` tables tie each
message to a single `response_id` with a `direction` column ("input" /
"output") and an `order` integer. This is a clean serialisation of "the
turn we just did" but it fails on three goals we now want first-class:

1. **Library-first semantics.** `llm` should be a Python library that
   models conversations correctly, with SQLite as one optional
   serializer used by the CLI. The current schema's coupling of
   messages to response rows is a tail-wagging-dog: it forces
   storage-shaped reasoning into the in-memory model.
2. **Stateless API continuation.** If LLM exposes an OpenAI-compatible
   chat completions endpoint, every request will arrive with the full
   message sequence. We must detect "this is a continuation of a
   sequence we've already logged" and store only the new tail —
   without the client telling us anything.
3. **Forking.** A user should be able to revisit any prior point in a
   conversation, branch off in a new direction, and pay zero
   incremental storage for the shared prefix.

All three problems collapse into the same data structure: an
**immutable, parent-linked, content-addressed message DAG**. The
git data model applied to conversation messages.

## Design summary

- Each `Message` is stored once, immutable, with a `parent_id` pointing
  at the previous message in its branch (NULL at the root) and a
  `content_hash` derived from a canonical serialization of the message.
- A "response" record is metadata about *one LLM call*: model used,
  duration, usage, errors, resolved model. It anchors to the head
  output message it produced and the head input message that prompted
  it. It does not own the messages.
- A "conversation" is a named pointer at a head message. Walking
  `parent_id` from the head reconstructs the full sequence.
- Continuation detection, fork-from-anywhere, and cross-database merge
  are all consequences of the data structure, not features bolted on.

## Python in-memory model

The pure-Python contract barely changes — that's the point.

### What stays the same

- `Message(role, parts, provider_metadata)` remains a value type.
- `TextPart`, `ReasoningPart`, `ToolCallPart`, `ToolResultPart`,
  `AttachmentPart` unchanged.
- `StreamEvent` unchanged.
- `Message.to_dict()` / `Message.from_dict()` unchanged.
- A conversation in memory is still a `list[Message]`.
- `model.prompt(messages=[...])` accepts a list of Messages.
- `response.messages` is the structured assistant turn.

### What changes

A new helper module (call it `llm.dag` or fold into `llm.parts`) adds:

```python
def canonical_message_json(msg: Message) -> bytes:
    """Deterministic JSON for a Message — input to content_hash."""
    d = {
        "role": msg.role,
        "parts": [_canonical_part(p) for p in msg.parts],
    }
    if msg.provider_metadata:
        d["provider_metadata"] = msg.provider_metadata
    return json.dumps(
        d,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def message_content_hash(msg: Message) -> str:
    return hashlib.sha256(canonical_message_json(msg)).hexdigest()
```

`_canonical_part` mostly delegates to `Part.to_dict()` but recursively
sorts dicts inside `provider_metadata`, normalizes
`AttachmentPart.attachment.content` to base64, and elides None/empty
fields consistently.

`Conversation` (the in-memory class) gains:

```python
class Conversation:
    head_message_id: Optional[str] = None  # set when persisted/loaded
    # ... existing fields ...
```

`Message` itself does **not** gain `id` or `parent_id` fields. Those
are storage concerns. Messages remain pure values; identity is
external (assigned by the storage layer or computed via content_hash).

This keeps the in-memory model usable without any DB. Two Messages
with identical content are `==`, even if they came from different
saved chains. That's correct for the value-type contract.

### Storage facade

A `MessageStore` (or methods on `Database`) provides:

```python
class MessageStore:
    def save_chain(
        self,
        messages: list[Message],
        starting_parent_id: Optional[str] = None,
    ) -> str:
        """Save messages as a chain. Returns head_message_id of the chain.

        Detects existing prefix matches: if the first N messages already
        exist as a chain rooted at starting_parent_id (which may be None
        for a root match), only the unmatched tail is inserted.
        """

    def load_chain(self, head_message_id: str) -> list[Message]:
        """Walk parent_id links from head, return chain in order."""

    def fork(
        self, source_message_id: str, name: Optional[str] = None
    ) -> str:
        """Create a new conversation pointing at source_message_id.
        Returns the new conversation_id."""

    def find_longest_existing_prefix(
        self, messages: list[Message]
    ) -> tuple[Optional[str], int]:
        """Used by stateless API continuation. Returns
        (last_matched_message_id, count_matched)."""
```

The CLI and any future API endpoint use these methods. Library users
who don't care about persistence ignore them and work directly with
`list[Message]`.

## SQL schema

### Tables introduced or reshaped

```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,                          -- ULID
    parent_id TEXT REFERENCES messages(id),       -- NULL at chain root
    content_hash TEXT NOT NULL,                   -- sha256 hex
    role TEXT NOT NULL,                           -- "user"/"assistant"/"system"/"tool"
    provider_metadata_json TEXT,
    created_at TEXT NOT NULL                      -- ISO-8601 UTC, when this row was first inserted
);
CREATE INDEX idx_messages_content_hash ON messages(content_hash);
CREATE INDEX idx_messages_parent_id ON messages(parent_id);
-- (parent_id, content_hash) is the lookup key for continuation detection;
-- a composite index also helps:
CREATE INDEX idx_messages_parent_hash ON messages(parent_id, content_hash);

CREATE TABLE message_parts (
    id TEXT PRIMARY KEY,                          -- ULID
    message_id TEXT NOT NULL REFERENCES messages(id),
    "order" INTEGER NOT NULL,
    part_type TEXT NOT NULL,                      -- text/reasoning/tool_call/tool_result/attachment/unknown
    content TEXT,                                 -- bulk text payload
    content_json TEXT,                            -- per-type structured JSON
    tool_call_id TEXT,
    server_executed INTEGER
);
CREATE UNIQUE INDEX idx_message_parts_message_order
    ON message_parts(message_id, "order");
```

Compared to current m023:

- `messages` loses `response_id`, `direction`, `order`. Gains
  `parent_id` and `content_hash`.
- `message_parts` is structurally unchanged.

### New `calls` table (one row per LLM call)

The existing `responses` table is left untouched — old data stays
queryable, no migration risk. New writes go to a new table called
`calls`. The name fits its actual role better (a row per LLM call,
not "the response data") and avoids confusion with the in-memory
`Response` Python class.

```sql
CREATE TABLE calls (
    id TEXT PRIMARY KEY,                          -- ULID
    conversation_id TEXT REFERENCES conversations(id),
    head_input_message_id TEXT REFERENCES messages(id),
    head_output_message_id TEXT REFERENCES messages(id),
    model TEXT NOT NULL,
    resolved_model TEXT,
    started_at TEXT NOT NULL,                     -- ISO-8601 UTC
    duration_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    token_details_json TEXT,
    prompt_json TEXT,                             -- redacted raw provider request
    response_json TEXT,                           -- redacted raw provider response
    error TEXT
);
CREATE INDEX idx_calls_conversation ON calls(conversation_id);
CREATE INDEX idx_calls_started_at ON calls(started_at);
CREATE INDEX idx_calls_head_input ON calls(head_input_message_id);
CREATE INDEX idx_calls_head_output ON calls(head_output_message_id);
```

Differences from the old `responses` table:

- No `prompt`, `system`, `response` text columns. Reconstructible by
  walking the DAG. Big space win — those were the bulk of row size.
- Adds `error` column for failed calls (today errors live elsewhere).
- `started_at` instead of `datetime_utc` — clearer intent and pairs
  naturally with `duration_ms`.

### `conversations` gains a column

```sql
ALTER TABLE conversations
    ADD COLUMN head_message_id TEXT
        REFERENCES messages(id);
```

`conversations.head_message_id` advances each time a turn is appended.
A conversation's full message list is reconstructed by walking
parent_id links from the head.

### `responses` table — frozen

Stays as-is. Migrations untouched. Existing `llm logs` queries
continue to work against historical rows. New code does not write to
it. The CLI's `llm logs` learns to read both tables: `calls` is
canonical going forward, `responses` is read-only historical data.
Eventually deprecate `responses` writes — but that's a follow-up, not
in scope here.

### What the relationships look like

```
conversations
  | head_message_id
  v
messages -- parent_id --> messages -- parent_id --> messages ...
  ^                                                     ^
  | head_input_message_id                               | head_output_message_id
  |                                                     |
  +--------- calls -------------------------------------+
                |
                v
            (model, usage, started_at, duration_ms, etc)

messages.id <----- message_parts.message_id (1:N, ordered)
```

### Timestamps

Two distinct timestamps live in the schema, with two distinct
purposes. Mixing them is a common pitfall.

**`messages.created_at`** — when this row was first inserted into the
DB. Set on insert; never updated; not affected by dedup hits. Useful
for: debugging, audit, garbage collection. Not useful for: "when did
this turn happen" — a message that was inserted at T=0 might be part
of a turn processed at T+5min if the client resends it.

**`calls.started_at` / `duration_ms`** — when the server actually
processed an LLM call. One row per call. This is the canonical
"when did this turn happen."

#### Worked example

Client sends `[system, user1, asst1, user2]` at T=0. Server processes,
generates `asst2`. DB writes:

```
messages: system   (id=A, parent=NULL, created_at=T0)
          user1    (id=B, parent=A,    created_at=T0)
          asst1    (id=C, parent=B,    created_at=T0)
          user2    (id=D, parent=C,    created_at=T0)
          asst2    (id=E, parent=D,    created_at=T0)
calls:    row K1 (head_input=D, head_output=E,
                  started_at=T0, duration_ms=1234)
```

Client sends `[system, user1, asst1, user2, asst2, user3]` at
T+5min. Server detects the prefix `[A..E]` already exists; only
`user3` is new. Server generates `asst3`. New writes:

```
messages: user3   (id=F, parent=E,    created_at=T+5min)
          asst3   (id=G, parent=F,    created_at=T+5min)
calls:    row K2 (head_input=F, head_output=G,
                  started_at=T+5min, duration_ms=…)
```

Lookups:

- "When was the chain ending at `asst2` processed?" → call with
  `head_output=E` → K1 → T=0.
- "When was the chain ending at `asst3` processed?" → call with
  `head_output=G` → K2 → T+5min.
- "When did the system message first appear on the server?" →
  `messages.created_at` of A → T=0.

#### Messages with no `calls` row

A client can inject assistant messages the server never generated
(replaying transcripts from elsewhere, or content from a different
LLM). Those get `messages` rows on save but no `calls` row, because
the server didn't process them. Their "when did this happen" is only
`messages.created_at`. The `calls` table records server processing,
not client-supplied content.

#### The same input message anchoring multiple calls

A user retries the same prompt to compare model outputs: multiple
`calls` rows with the same `head_input_message_id` but different
`head_output_message_id`s, with different `started_at` values. All
recorded; the DAG can have multiple children of the same parent
(forks happen automatically).

#### Pure dedup hits

A repeat client request whose entire sequence already exists
(retries, idempotent reposts) writes zero new `messages` rows but
should still write a `calls` row to record that a call happened with
real wall-clock cost. Worth it for billing/audit; avoidable if the
caller explicitly opts out.

## Algorithms

### Save a chain (with continuation dedup)

```python
def save_chain(db, messages, starting_parent_id=None):
    parent = starting_parent_id
    for msg in messages:
        h = message_content_hash(msg)
        existing = db.execute(
            "SELECT id FROM messages "
            "WHERE content_hash = ? AND parent_id IS ? LIMIT 1",
            [h, parent],
        ).fetchone()
        if existing:
            parent = existing[0]
            continue
        new_id = str(monotonic_ulid()).lower()
        db["messages"].insert({
            "id": new_id,
            "parent_id": parent,
            "content_hash": h,
            "role": msg.role,
            "provider_metadata_json":
                json.dumps(msg.provider_metadata, sort_keys=True)
                if msg.provider_metadata else None,
        })
        for order, part in enumerate(msg.parts):
            row = part_to_row(new_id, order, part)
            row["id"] = str(monotonic_ulid()).lower()
            db["message_parts"].insert(row)
        parent = new_id
    return parent
```

Notes:

- The `(content_hash, parent_id)` lookup is the dedup pivot. A message
  is uniquely identified by *what it says* and *what came before it*.
  Two identical system prompts at different chain positions are
  different rows; an identical system prompt at the same chain
  position is one row.
- `parent IS ?` works for both NULL and non-NULL because we use
  sqlite3's `?` binding (Python's `None` becomes NULL for `IS`).

### Continuation detection (stateless API)

```python
def find_longest_existing_prefix(db, messages):
    parent = None
    matched = 0
    for msg in messages:
        h = message_content_hash(msg)
        existing = db.execute(
            "SELECT id FROM messages "
            "WHERE content_hash = ? AND parent_id IS ? LIMIT 1",
            [h, parent],
        ).fetchone()
        if not existing:
            break
        parent = existing[0]
        matched += 1
    return parent, matched

def save_with_dedup(db, messages):
    parent, matched = find_longest_existing_prefix(db, messages)
    return save_chain(db, messages[matched:], starting_parent_id=parent)
```

When the OpenAI-compatible endpoint receives a request:

1. Run `save_with_dedup(messages)` — this either writes nothing
   (sequence already exists) or writes only the unseen tail.
2. The returned head is the input head for the call.
3. Generate the assistant reply, save it as a child of the input head,
   insert a `calls` row with `head_input_message_id` and
   `head_output_message_id` set, plus `started_at` / `duration_ms` /
   usage / model.
4. Optionally update a "session" or "conversation" head pointer if the
   client supplied one.

No client cooperation needed; the chain structure is the dedup key.

### Forking

```python
def fork(db, source_message_id, name=None):
    new_conv_id = str(monotonic_ulid()).lower()
    db["conversations"].insert({
        "id": new_conv_id,
        "head_message_id": source_message_id,
        "name": name,
        "model": _conversation_model_for(db, source_message_id),
    })
    return new_conv_id
```

Subsequent prompts on the new conversation save with
`starting_parent_id = current_head`. New messages diverge from the
shared prefix automatically. Storage cost: one `conversations` row.

### Loading a conversation

```python
def load_chain(db, head_message_id):
    chain_rows = []
    cur = head_message_id
    while cur is not None:
        row = db.execute(
            "SELECT * FROM messages WHERE id = ?", [cur]
        ).fetchone()
        chain_rows.append(row)
        cur = row["parent_id"]
    chain_rows.reverse()
    out = []
    for r in chain_rows:
        parts = load_message_parts(db, r["id"])
        pm = (json.loads(r["provider_metadata_json"])
              if r["provider_metadata_json"] else None)
        out.append(Message(role=r["role"], parts=parts,
                           provider_metadata=pm))
    return out
```

For Conversation history reconstruction during a `model.prompt()`
call: walk from `conversation.head_message_id`, build the
`list[Message]`, hand to the provider adapter as
`prompt.messages`-equivalent prior history.

### Cross-database merge

Because every `messages.id` is a ULID and `parent_id` references
`messages.id` by exact string, two databases can be merged by:

1. `INSERT OR IGNORE` all `messages` rows from B into A. ULIDs don't
   collide; identical `content_hash` + `parent_id` rows would already
   share an id only if they came from the same source database.
2. Same for `message_parts`, `calls`, `conversations`.

Identical content from independent databases will *not* automatically
collapse into one row (different ULIDs). A second-pass merge step can
walk both DBs, find pairs with matching `(content_hash, parent_id)`,
and rewrite refs to a canonical id. This is opt-in; the basic merge
works without it.

## Migration story

Branch hasn't shipped, so the m023 schema can be replaced rather than
upgraded. Two acceptable approaches:

**Option A — Replace m023 in place.** Edit `m023_messages_table` to
emit the new schema. Anyone who already ran m023 has empty
messages/message_parts tables (per user's "ignore prior logs"
position); easiest for them is to drop those tables and rerun, or
recreate the DB.

**Option B — Add m024 that drops m023 tables and recreates.** Cleaner
audit trail (the change is a real migration). Slightly worse for
anyone using a dev DB on the parts branch, but they were warned.

Recommendation: **Option A**, given the branch is unpublished and
nobody outside development is reading m023 yet. If we'd shipped
m023 to anyone who matters, Option B becomes mandatory.

The legacy `parts` table from m022 stays as dead code (already
unread/unwritten). Drop in a follow-up cleanup migration if desired.

## Subtleties and decisions

### Canonical serialization correctness

The hash is a contract. Once shipped, changing canonicalization
breaks dedup forever. Lock down:

- `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`.
- All dicts inside `provider_metadata` are recursively sorted.
- `AttachmentPart.attachment.content` (raw bytes) is base64 with
  standard padding.
- Numbers: ints stay ints; floats are forbidden inside
  `provider_metadata` to avoid representation drift (validate at
  attach time).
- None vs missing: omit keys whose value is None.

Add a `tests/test_canonical.py` that pins example
`(message → canonical_json → content_hash)` triples as snapshot
fixtures. Any code change that perturbs canonicalization fails this.

### Streaming and pending content_hash

A streaming response can't be hashed until streaming completes.
Options:

- **Hold off the insert.** Buffer the assembled assistant Message
  in memory; insert the row(s) only after the response is `_done`.
  Simple, no partial states, the only cost is no live row to query
  during streaming. Picked.
- **Insert with NULL hash, update on done.** Allows live querying
  but introduces a partially-valid state and complicates the
  dedup index.

Go with the first.

### Multiple output messages per call

`StreamEvent.message_index` lets a call emit multiple assistant
messages (server-side tool execution patterns). The chain becomes:

```
input_head -> assistant_message_0 -> assistant_message_1 -> ...
```

`calls.head_output_message_id` points at the *last* assistant
message. Walking back from there gives the call's full output.

### Tool call ids and content hashing

`ToolCallPart.tool_call_id` is opaque per-execution. Two re-runs of
the same tool will produce different ids and therefore different
content hashes — they're correctly stored as different messages even
if everything else matches. Good. Don't try to be clever.

### Provider metadata in the hash

Yes, in. `provider_metadata` is part of message identity for the
purposes of replay. Anthropic `signature` blobs, Gemini
`thoughtSignature`, OpenAI Responses `encrypted_content` all end up
in the hash. This means the same plain text from the same model with
two different per-turn encrypted blobs gets two different hashes —
correct, because the request you'd build to continue from each
differs.

### What about `calls.head_input_message_id`?

Why not just walk from `head_output_message_id` back? Two reasons:

1. The boundary between input and output messages isn't intrinsic to
   the chain — without an explicit marker, there's no way to know "the
   model started talking here." `head_input_message_id` is that marker.
2. Some calls have empty output (errors, refusals) but still consumed
   an input chain — we want to record what the request was.

Both pointers cost 26 bytes per `calls` row. Worth it.

### Schema migrations and rewriting

Once shipped, the DAG schema is hard to evolve — every row references
every previous row. Be conservative about adding required columns to
`messages` post-ship. Optional columns and side tables are fine.

### Locking and concurrency

Two writers might race to insert the same (content_hash, parent_id).
Use SQLite's transaction + a `UNIQUE` index on
`(parent_id, content_hash)` to prevent duplicate inserts. The
`save_chain` algorithm's `SELECT … LIMIT 1` then re-`SELECT` on
conflict to grab the winner's id.

```sql
CREATE UNIQUE INDEX idx_messages_parent_hash_unique
    ON messages(parent_id, content_hash);
```

#### The NULL-parent uniqueness footgun

SQLite treats NULLs as distinct in unique constraints. Two root
messages with the same `content_hash` and `parent_id = NULL` both
satisfy the uniqueness check and both insert. The dedup index that
protects every non-root message silently does nothing at the root.

This matters because the root is *the* common collision point. Most
conversations start with the same system prompt. Every one of them
would fork a parallel root chain, and every subsequent turn builds on
a different root, so downstream dedup also fails. The "periodic GC
pass can collapse duplicates" escape hatch is not acceptable here —
the common case would be permanently broken between GC runs, and
every reader would have to tolerate multiple rows for "the same
message."

**Decision: use a sentinel root id.** Reserve the literal string
`"root"` as a message id. `parent_id` is NOT NULL; chain roots point
at the sentinel. The unique index then works uniformly, including at
the root. The sentinel row itself is inserted once at migration time
with a fixed id and empty content; it never participates in hashing
or chain walks (the loader stops when it sees `parent_id = "root"`).

Cost: one reserved id, one row, one line in the loader. Benefit:
dedup is correct by construction at every chain position.

## What this lets us deprecate

- `messages.response_id`, `direction`, `order` columns from m023. Gone.
- The "every message lives inside a turn" mental model. A message is
  a chain node first; turns are how we group inserts.
- Eventually, the legacy `responses` table itself once consumers
  migrate. Until then it's frozen and read-only.

## Out of scope (for now)

- **Multi-parent merges.** Some agent patterns weave multiple branches
  back together. Could add a `message_parents` join table later. YAGNI.
- **Content-addressed blob storage.** A `blobs` table keyed by
  sha256, with `message_parts.content` becoming `content_hash`,
  would dedup repeated text payloads (system prompts, tool outputs).
  Orthogonal to the DAG; can be layered on later.
- **Garbage collection.** Forking and re-saving creates orphan
  branches if conversations are deleted. A `gc` command that walks
  reachable messages from all conversation heads and prunes the rest
  is straightforward but not pre-ship.
- **Cross-model continuation.** A conversation might be continued on
  a different model. The chain structure handles this trivially
  (messages don't know which model produced them); the `calls` rows
  record per-call model. Just noting it works.

## Questions for the next pass

1. Where does `MessageStore` live — a new module, or methods on an
   existing `Database` class? Lean toward a new `llm.storage` module
   that the CLI imports; library users can import too if they want
   persistence.
2. Should `Message` get an optional `id` field after all, populated by
   the loader, ignored by the saver? Helps when a caller wants to
   reference "this exact message I just got from load_chain". Could
   also be a side dict. Lean toward keeping Message pure.
3. Default behavior for `model.prompt(messages=[...])` when no
   conversation is given: should it auto-dedup against the global
   message DAG? Probably yes — there's no downside, and it's the
   only path stateless API endpoints will go through.
4. How does `llm logs` UI render forks? A tree view? Default to the
   current branch and a `--show-forks` flag? Worth a separate UX
   pass.
5. How does the in-memory `Conversation` know its `head_message_id`
   when constructed via `model.conversation()` (no DB involved)?
   Probably leave it `None` until the first `log_to_db()` and have
   `log_to_db()` set it. Subsequent saves use it.

## Suggested implementation sequence

1. Lock canonical serialization + hash. Add canonicalization tests.
2. Replace m023 schema (new `messages` shape, new `message_parts`,
   new `calls` table, `conversations.head_message_id` column).
   Implement `MessageStore.save_chain` and `load_chain`. Wire
   `log_to_db` to write to `messages` + `message_parts` + `calls`
   instead of the old `responses`/`messages`-with-direction shape.
   Keep writing the legacy `responses` row in parallel for one release
   for backward-compat. Wire `Response.from_row` to load via chains.
3. Implement `find_longest_existing_prefix` and rebuild
   `Conversation` history reconstruction to use it.
4. Implement `fork`. Add CLI `llm fork <message_id>` and `llm chat -c
   <conversation_id>` (probably already works).
5. Update docs and the plugin upgrade guide to describe the new
   storage shape (mostly transparent — plugins still produce
   `list[Message]` and don't touch storage).
6. Defer: blob dedup, GC, cross-DB merge tooling, `llm logs` tree
   view.
