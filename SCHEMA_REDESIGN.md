# Design proposal: persisting Messages and Parts to SQLite

Status: proposal (0.32 alpha series)

This is the final stage before a non-alpha release: persisting the new
Message/Part shape (`llm/parts.py`, `llm/serialization.py`) to a redesigned
set of database tables, such that a logged response is fully
round-trippable — `log_to_db()` followed by `from_row()` must reproduce
the same structure that `Response.to_dict()` / `Response.from_dict()`
round-trips today.

## Why the current tables can't round-trip the new shape

The current schema stores a flattened projection of each response:

- `responses.prompt` / `responses.system` / `responses.response` — text only
- `responses.reasoning` — reasoning *concatenated to a single string* (m022)
- `tool_calls` / `tool_results` — separate tables, but with no part
  ordering, no `server_executed` flag, no `provider_metadata`
- nothing stores message-level or part-level `provider_metadata` at all

That loses exactly the data the new code paths depend on:

- **`provider_metadata`** carries Anthropic `signature`, Gemini
  `thoughtSignature`, OpenAI `encrypted_content` — data that *must be
  echoed back on the next request*. Without it, `llm -c` silently degrades
  reasoning conversations, and resuming a `PauseChain` from pending tool
  calls (#1482) across a process boundary is impossible.
- **Part ordering and interleaving** (text → tool_call → text) is
  unrecoverable from the flattened columns.
- **Redacted-reasoning markers** (`ReasoningPart(redacted=True, text="")`)
  have no representation.
- **`server_executed` tool calls** (Anthropic web search, Gemini code
  execution) are indistinguishable from framework-executed ones.
- **Multiple assistant messages per response** (`message_index`) collapse
  into one blob.

`load_conversation()` in `cli.py` currently has to *re-synthesize* the
message chain from the legacy columns with a comment apologizing for it.
The new schema makes the stored form the authoritative form.

## Design constraints

1. **Lossless round trip.** `rows → Message` must reproduce
   `Message.to_dict()` exactly. The canonical wire format in
   `llm/serialization.py` is the contract; the tables are a normalized
   projection of it, not a second format that can drift.
2. **No quadratic storage.** The `Prompt.messages` invariant says every
   response's prompt contains the *full* chain including history. Storing
   that verbatim per turn means turn N stores N copies of turn 1.
3. **Queryable in plain SQLite/Datasette.** Typed columns for the common
   questions ("all tool calls", "all reasoning", "which responses used
   this image"), JSON1-queryable text columns for the open-ended parts.
4. **Keep what works.** Content-addressing (attachments/fragments are
   sha256, schemas blake2b, tools hashed), sqlite-utils migrations, the
   `responses` table as the unit of `llm logs`, FTS on prompt/response,
   and the fragments/tools/schemas tables — all unchanged.

## Core idea: content-addressed messages

`parts.py` states the principle outright:

> These types are pure values — identity (ids, parent links, storage
> keys) is a storage concern that lives elsewhere. Two Messages with
> identical content are equal.

So messages get content-hash primary keys, exactly like fragments and
attachments already do. The repeated history in each turn's input chain
then **dedupes automatically**: turn 50's input chain is 50 tiny link
rows pointing at message rows that already exist. Identity lives in the
link table (`response_messages`), values live once in `messages`/`parts`.

This also makes every response *independently* round-trippable — no chain
reconstruction at load time, which matters because callers may pass an
explicit `messages=` list that is not an extension of stored history.

## New tables

Four new tables, created by migration `m023_messages_tables`:

### `messages`

| column              | type | notes                                      |
|---------------------|------|--------------------------------------------|
| `id`                | TEXT PK | content hash (see below)                |
| `role`              | TEXT | `system` / `user` / `assistant` / `tool`   |
| `provider_metadata` | TEXT | JSON, null when absent                     |

**Hash:** `sha256` of the canonical JSON of `Message.to_dict()` —
`json.dumps(..., sort_keys=True, separators=(",", ":"))` — with one
substitution: every nested attachment dict is replaced by
`{"id": attachment.id()}` so multi-megabyte binaries hash fast and
identical content dedupes regardless of whether it arrived via `path`,
`url`, or `content`. `to_dict()` already omits defaults/absent keys, so
the canonical form is stable by construction.

### `parts`

One row per Part, single-table with nullable per-type columns
(five part types don't justify five tables; NULLs are free in SQLite):

| column              | type    | used by                                  |
|---------------------|---------|------------------------------------------|
| `id`                | INTEGER PK | surrogate, for `part_attachments` FK  |
| `message_id`        | TEXT FK → messages | —                             |
| `order`             | INTEGER | position within message; `UNIQUE(message_id, "order")` |
| `type`              | TEXT    | `text` / `reasoning` / `tool_call` / `tool_result` / `attachment` |
| `text`              | TEXT    | text, reasoning                          |
| `redacted`          | INTEGER | reasoning (the opaque-reasoning marker)  |
| `name`              | TEXT    | tool_call, tool_result                   |
| `arguments`         | TEXT    | tool_call (JSON)                         |
| `output`            | TEXT    | tool_result                              |
| `tool_call_id`      | TEXT    | tool_call, tool_result (indexed)         |
| `server_executed`   | INTEGER | tool_call, tool_result                   |
| `exception`         | TEXT    | tool_result                              |
| `instance_id`       | INTEGER FK → tool_instances | tool_result, nullable — see note |
| `attachment_id`     | TEXT FK → attachments | attachment (the 1:1 case)  |
| `provider_metadata` | TEXT    | all (JSON)                               |

Note on `instance_id`: `ToolResultPart` deliberately doesn't model
Toolbox instances (identity again), but the instance used is worth
auditing. It is populated at log time by correlating
`prompt.tool_results` with the part via `tool_call_id`, exactly as
`log_to_db` tracks it today. It does not participate in the message hash
and is not part of the round trip — same as current behavior.

### `part_attachments`

Ordered attachment lists for `ToolResultPart.attachments`:

| column          | type    |
|-----------------|---------|
| `part_id`       | INTEGER FK → parts |
| `attachment_id` | TEXT FK → attachments |
| `order`         | INTEGER |

PK `(part_id, "order")`. The existing `attachments` table is reused
unchanged — it is already content-addressed with `replace=True` writes.
`AttachmentPart` keeps the simpler 1:1 `parts.attachment_id` column so
the common "show me the image" query is a single join.

### `response_messages`

The identity layer — which messages a response saw and produced, in order:

| column       | type |
|--------------|------|
| `response_id`| TEXT FK → responses |
| `message_id` | TEXT FK → messages  |
| `scope`      | TEXT — `input` or `output` |
| `order`      | INTEGER — position within scope |

PK `(response_id, scope, "order")`, index on `message_id`.

- `scope='input'` rows are `response.prompt.messages` — the full
  authoritative chain, in order. The same `message_id` may legitimately
  appear at two orders (a user who says "ok" twice).
- `scope='output'` rows are the assembled response messages. Multiple
  assistant messages per response (Anthropic server-side tool execution)
  are just multiple output rows in order — `message_index` needs no
  column because `List[Message]` order is the only thing `to_dict()`
  preserves anyway.

Link rows grow O(N²/2) across a conversation, but each is three short
values; a 100-turn chat is ~5,000 link rows against singly-stored
content. The alternative — storing only per-turn deltas and rebuilding
chains at read time — is what we do today, and it is precisely what
cannot represent explicit `messages=` lists or survive the
provider_metadata requirements. Correctness wins; dedupe keeps it cheap.

## Changes to existing tables

### `responses` — kept, slimmed in meaning

`id` (ULID), `model`, `resolved_model`, `conversation_id`,
`options_json`, `schema_id`, `prompt_json`, `response_json`,
`duration_ms`, `datetime_utc`, `input_tokens`, `output_tokens`,
`token_details` all keep their current roles.

`prompt`, `system`, `response`, `reasoning` remain as **derived
convenience columns** — written from the same data that produces the
message rows, so `llm logs`, FTS (`responses_fts` on prompt/response),
and every existing Datasette dashboard keep working untouched. They are
documented as projections; `response_messages` is the source of truth.

### Superseded (kept for legacy rows, no longer written)

`tool_calls`, `tool_results`, `tool_results_attachments`, and
`prompt_attachments` are superseded by `parts`. Following the m009/m010
precedent, the migration does not drop or rewrite them — old rows remain
readable through the existing `from_row` fallback path. For query
compatibility the migration creates views:

```sql
CREATE VIEW v_tool_calls AS
  SELECT rm.response_id, p.name, p.arguments, p.tool_call_id, p.server_executed
  FROM parts p
  JOIN response_messages rm ON rm.message_id = p.message_id AND rm.scope = 'output'
  WHERE p.type = 'tool_call';

CREATE VIEW v_tool_results AS
  SELECT rm.response_id, p.name, p.output, p.tool_call_id, p.exception, p.instance_id
  FROM parts p
  JOIN response_messages rm ON rm.message_id = p.message_id AND rm.scope = 'input'
  WHERE p.type = 'tool_result';
```

(Tool *calls* are model output; tool *results* arrive as input on the
next response — the scope filters encode that.)

### Unchanged

- `conversations` — unchanged.
- `fragments`, `fragment_aliases`, `prompt_fragments`, `system_fragments`
  — unchanged. Fragments are a text-expansion feature that operates
  *before* messages are built (`Prompt.prompt` concatenates them), so
  they stay keyed on `response_id` for provenance/`condense_json`
  replacement, orthogonal to the message layer.
- `tools`, `tool_responses`, `tool_instances` — unchanged. Tool
  *definitions* offered to a prompt are not part of the message chain.
- `schemas`, `attachments` — unchanged.
- Embeddings tables — out of scope.

## Write path (`log_to_db`)

1. Insert attachments first (`replace=True`, content-addressed — as now).
2. `ensure_message(db, message)`: compute the hash; if the `messages` row
   is new, insert it plus its `parts` rows (and `part_attachments`) in
   the same transaction. Existing hash → skip entirely. Mirrors
   `ensure_fragment` / `ensure_tool`.
3. Insert `response_messages` links: one per `prompt.messages` entry
   (`input`), one per `_messages_now()` entry (`output`).
4. Write the `responses` row including the derived text columns
   (`prompt`, `system`, `response`, `reasoning`) exactly as today.
5. Stop writing `tool_calls` / `tool_results` / `prompt_attachments` /
   `tool_results_attachments`.

Fragments, tools, schemas, `condense_json` replacements: unchanged.

## Read path (`from_row` / `load_conversation`)

If `response_messages` rows exist for the response (new-style row):

- input messages → `Prompt(messages=input, system=row["system"],
  options=...)` — the explicit-messages path, which is already
  authoritative under the `Prompt.messages` invariant
- output messages → `response._loaded_messages`, with `_chunks` rebuilt
  from text parts — exactly what `_response_from_dict` does today

Otherwise fall back to the current legacy reconstruction. This lets
`load_conversation` delete its chain-rebuilding patch for new rows: the
stored input chain *is* the chain, with signatures and redacted markers
intact, which is what makes `llm -c` onto a reasoning model and chain
resume from pending tool calls actually correct.

## Round-trip guarantee

The contract is stated in terms of the canonical wire format:

```
rows_to_message(message_to_rows(m)).to_dict() == m.to_dict()
```

for every Part type with every optional field present and absent. Tests:

1. **Property/parametrized part round trip** — all five part types ×
   optional-field combinations (`provider_metadata`, `redacted`,
   `server_executed`, `exception`, attachments by url/path/content).
2. **Full response round trip** — build a Response covering interleaved
   text/reasoning/tool-call parts and multi-message output;
   `log_to_db()` then `from_row()`; assert `to_dict()` equality
   (including `usage` and `datetime_utc`).
3. **Dedupe** — log a 3-turn conversation; assert each distinct message
   has exactly one `messages` row and link counts are 1+3+5 / outputs.
4. **Hash stability** — golden hashes for fixed messages, so an
   accidental change to canonical serialization fails loudly rather than
   silently forking the dedupe space.
5. **Legacy fallback** — fixture DB with pre-m023 rows still loads, and
   `llm -c` still works against it.

## Migration and rollout

- `m023_messages_tables`: create the four tables, indexes, and views.
  No automatic rewriting of historical data (m009 precedent: never
  destroy or churn user data in a migration).
- Optional backfill as an explicit command — `llm logs backfill-messages`
  — which runs the legacy `from_row` reconstruction per response and
  feeds it through `ensure_message`. Idempotent by construction
  (content hashes + `INSERT OR IGNORE`). Old rows it can't fully
  reconstruct (they never stored metadata) backfill as faithfully as the
  legacy columns allow, which is no worse than reading them today.

## Example queries this unlocks

```sql
-- Reasoning emitted per response, with redaction markers visible
SELECT rm.response_id, p."order", p.redacted, p.text
FROM parts p
JOIN response_messages rm ON rm.message_id = p.message_id AND rm.scope = 'output'
WHERE p.type = 'reasoning';

-- Every response that ever saw a given attachment, input or output
SELECT DISTINCT rm.response_id, rm.scope
FROM parts p
JOIN response_messages rm USING (message_id)
WHERE p.attachment_id = :attachment_id;

-- Tool calls with their matching results, across the turn boundary
SELECT c.name, c.arguments, r.output, r.exception
FROM v_tool_calls c LEFT JOIN v_tool_results r USING (tool_call_id);
```

## Open questions

1. **Table naming** — `parts` is short and matches `llm/parts.py`;
   `message_parts` is more self-describing in a shared logs.db.
2. **FTS over parts** — should `parts.text` / `parts.output` get their
   own FTS table so `llm logs -q` can find text inside tool output and
   reasoning? Proposed as a follow-up, not part of this migration.
3. **`prompt_json` / `response_json`** — the raw provider payloads stay
   for audit/debugging, but with the structured shape stored faithfully
   they could become opt-in (`--log-raw`?) in a future release to cut
   database size.
