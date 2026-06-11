# Design proposal: persisting Messages and Parts to SQLite

Status: proposal, revision 4 (0.32 alpha series)

This is the final stage before a non-alpha release: persisting the new
Message/Part shape (`llm/parts.py`, `llm/serialization.py`) to a redesigned
set of database tables, such that a logged response is fully
round-trippable — `log_to_db()` followed by `from_row()` must reproduce
the same structure that `Response.to_dict()` / `Response.from_dict()`
round-trips today.

How this proposal got here:

- **Revision 1** stored content-addressed messages/parts with a flat
  per-response link table.
- **Revision 2** replaced the link table with a **node tree**: positions
  point at their parent, a chain is a root-to-leaf path, a response
  records the leaf it sent and the leaf it produced.
- **Revision 3** added a clean break: new table names, no writes to or
  compatibility with the legacy tables — at the cost of making existing
  history invisible to `llm logs` until an explicit backfill.
- **Revision 4** (this one) fixes that cost: the legacy `responses`
  table is **renamed to `responses_archive`** — freeing the natural
  name for the new table — and a union view lets `llm logs` keep
  returning old and new rows together. Old conversations are lazily
  backfilled the first time `llm -c` touches them. New code never
  writes legacy shapes; nothing is ever dropped.

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
2. **Linear storage.** The `Prompt.messages` invariant says every
   response's prompt contains the *full* chain including history. An
   ongoing conversation must cost O(new content) per turn, not O(chain
   length) — including when llm is serving a stateless protocol (an
   OpenAI-compatible chat completions endpoint) where the client
   re-sends the entire history on every request.
3. **Branching is representable.** Regenerating from an earlier point,
   a client echoing a degraded copy of an assistant message, or two
   sessions diverging from a shared prefix should be forks in a tree,
   not duplicated or orphaned data.
4. **Old logs stay visible.** `llm logs` must keep returning
   pre-upgrade history, and `llm -c` must keep working against
   pre-upgrade conversations, without requiring the user to run
   anything first. The logs database is a personal archive; an upgrade
   that hides it is not acceptable.
5. **Queryable in plain SQLite/Datasette.** Typed columns for the common
   questions ("all tool calls", "all reasoning", "which responses used
   this image"), JSON1-queryable text columns for the open-ended parts.
6. **Clean break for writes; reuse of value tables.** New code never
   writes the legacy shapes. The content-addressed value stores
   (`attachments`, `fragments`, `fragment_aliases`, `schemas`, `tools`,
   `tool_instances`) are reused as-is — old and new rows coexist
   harmlessly in a content-addressed table, and reuse keeps
   fragment/attachment dedupe spanning the upgrade.

## The archive rule

The legacy `responses` table is renamed to **`responses_archive`** — a
metadata-only `ALTER TABLE ... RENAME`, instant at any size, and
nothing is destroyed. That frees the natural name: the new table is
simply `responses`. The legacy satellite tables (`tool_calls`,
`tool_results`, `prompt_attachments`, `tool_results_attachments`,
`prompt_fragments`, `system_fragments`, `tool_responses`) keep their
names — their `response_id` values still resolve against the archive,
none of their names collide with the new family, and the only code
that reads them is the backfill.

`conversations` is **reused, not renamed**: its shape (`id`, `name`,
`model`) is unchanged in the new design, so old and new conversations
live in one table and conversation ids stay continuous across the
upgrade — which is what lets `llm -c` continue a pre-upgrade
conversation at all.

After the rename, new code:

- writes only the new family;
- reads only the new family on the hot path;
- lists history through a **union view** spanning both eras;
- lazily backfills a conversation from the archive the first time it
  is continued.

What this buys, relative to maintaining in-place compatibility
(revision 2):

- **A near-pure migration.** One rename plus `CREATE TABLE`s. No
  `add_column`/`transform()` against populated tables, no FTS rebuild
  dance (m014 is the precedent for `transform()` silently dropping FTS
  config). The new table's FTS is defined once, on an empty table.
- **One hot read path.** `from_row` has no "new-style or legacy?"
  branch. The legacy reconstruction logic is quarantined inside the
  backfill module, where it can eventually be deleted.
- **Free column design.** `first_input_node_id` goes on the new
  `responses` table from day one, deleting the contorted "new input
  since the previous leaf" SQL that compatibility forced in revision 2.
- **A table-merge cleanup.** `prompt_fragments` and `system_fragments`
  were always one relation with a type flag — `FRAGMENT_SQL` in
  `models.py` unions them back together with a synthesized
  `fragment_type` column. The new schema stores them that way.

And relative to revision 3's invisible-until-backfill: constraint 4 is
satisfied with zero user action, which was the whole point.

## Core idea: content-addressed values, tree-shaped identity

`parts.py` states the principle outright:

> These types are pure values — identity (ids, parent links, storage
> keys) is a storage concern that lives elsewhere. Two Messages with
> identical content are equal.

The schema takes both halves of that sentence literally, as two layers:

**Values** — `messages` and `parts` rows are content-addressed: the
primary key is a hash of the canonical serialized form, exactly like
fragments and attachments today. Identical content is stored once,
globally, regardless of which conversation it appears in.

**Identity** — a `nodes` table gives content a *position*: each node
points at its parent node and at the message occupying that position.
A conversation chain is the path from a root (parent `NULL`) to a leaf.
A response records two pointers: the leaf of the chain it sent
(`input_node_id`) and the leaf of the chain after its output messages
were appended (`output_node_id`). The next turn extends
`output_node_id`. Same message under two different parents = two nodes,
one `messages` row.

Appending a turn therefore writes O(1) rows: nodes for the new input
message(s), nodes for the output message(s), one `responses` row. The
shared history is never touched. Forks are just siblings. This is the
shape llm had in embryo as `reply_to_id` (migrations m006–m008) and the
shape of the OpenAI Responses API's `previous_response_id` — applied at
message granularity rather than response granularity.

## The new tables

All created by migration `m023_messages_tables`; all writes go here and
nowhere else.

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

### `nodes`

The identity layer — positions in conversation trees:

| column       | type | notes                                          |
|--------------|------|------------------------------------------------|
| `id`         | TEXT PK | ULID, consistent with conversation/response ids |
| `parent_id`  | TEXT FK → nodes | `NULL` for roots                    |
| `message_id` | TEXT FK → messages | the value at this position       |
| `depth`      | INTEGER | denormalized: 0 for roots, parent + 1       |

Index `(parent_id, message_id)` — this is the lookup that makes prefix
walking cheap. Nodes are deduplicated on that pair by an
`ensure_node(db, parent_id, message_id)` helper (lookup-or-insert; the
application handles the `parent_id IS NULL` root case, since SQLite
unique indexes treat NULLs as distinct). Two responses that extend the
same leaf with the same message share a node; two conversations with
identical openings share a path. Nodes are **immutable** once written.

`depth` exists so "first N messages" and chain ordering don't require
counting recursion steps, and so history/input/output scopes can be
separated with comparisons (see the chain view).

### `responses` (new)

One row per model call, under the natural name freed by the archive
rename. Ids are ULIDs (`Response.id`), as they have been since m010 —
which matters for the union view (see below):

| column                | type | notes                                     |
|-----------------------|------|--------------------------------------------|
| `id`                  | TEXT PK | ULID (`Response.id`)                    |
| `model`               | TEXT |                                            |
| `resolved_model`      | TEXT | nullable                                   |
| `conversation_id`     | TEXT FK → conversations |                        |
| `input_node_id`       | TEXT FK → nodes | leaf of `prompt.messages` as sent; `NULL` for an empty chain |
| `first_input_node_id` | TEXT FK → nodes | first node of *this turn's new* input (after inherited history); `NULL` when the turn added no new input |
| `output_node_id`      | TEXT FK → nodes | leaf after appending `_messages_now()`; `NULL` if no output (error/cancelled) |
| `options_json`        | TEXT | JSON                                       |
| `schema_id`           | TEXT FK → schemas |                              |
| `prompt`              | TEXT | derived: this turn's user prompt text      |
| `system`              | TEXT | derived: system prompt text                |
| `response`            | TEXT | derived: concatenated output text parts    |
| `reasoning`           | TEXT | derived: concatenated visible reasoning    |
| `prompt_json`         | TEXT | raw provider request payload (condensed)   |
| `response_json`       | TEXT | raw provider response payload (condensed)  |
| `duration_ms`         | INTEGER |                                         |
| `datetime_utc`        | TEXT |                                            |
| `input_tokens`        | INTEGER |                                         |
| `output_tokens`       | INTEGER |                                         |
| `token_details`       | TEXT | JSON                                       |

The path from root to `input_node_id` *is* `prompt.messages`. The
segment from (exclusive) `input_node_id` to (inclusive)
`output_node_id` is the response's output messages. The next turn
extends `output_node_id`. A regenerated turn extends the same parent —
a sibling branch, visible in the data instead of impossible to express.

The derived text columns are projections kept for `llm logs` rendering
speed and FTS — defined once, on this empty table, as
`enable_fts(["prompt", "response"], create_triggers=True)`. The node
tree is the source of truth. The column set deliberately matches the
archive's so the union view is a straight `UNION ALL`.

### `response_fragments`

Merges the legacy `prompt_fragments` + `system_fragments` pair into the
single relation it always was:

| column          | type | notes                          |
|-----------------|------|--------------------------------|
| `response_id`   | TEXT FK → responses |                 |
| `fragment_id`   | INTEGER FK → fragments |              |
| `fragment_type` | TEXT | `prompt` or `system`           |
| `order`         | INTEGER |                             |

PK `(response_id, fragment_type, "order")` — the same fragment may
appear at multiple orders (issue #863). Fragments remain a
text-expansion feature that operates *before* messages are built;
these rows are provenance for `condense_json` and `llm logs --expand`.

### `response_tools`

Replaces `tool_responses` — which tool *definitions* were offered:

| column        | type |
|---------------|------|
| `response_id` | TEXT FK → responses |
| `tool_id`     | INTEGER FK → tools |

PK `(response_id, tool_id)`.

### The union view: old and new logs together

```sql
CREATE VIEW all_responses AS
SELECT id, conversation_id, model, resolved_model, prompt, system,
       response, reasoning, schema_id, options_json, prompt_json,
       response_json, duration_ms, datetime_utc,
       input_tokens, output_tokens, token_details,
       0 AS archived
FROM responses
UNION ALL
SELECT id, conversation_id, model, resolved_model, prompt, system,
       response, reasoning, schema_id, options_json, prompt_json,
       response_json, duration_ms, datetime_utc,
       input_tokens, output_tokens, token_details,
       1 AS archived
FROM responses_archive
WHERE id NOT IN (SELECT id FROM responses);
```

`llm logs list` reads this view instead of a table. Both eras use ULID
ids, so `ORDER BY id` remains chronological across the boundary. The
`archived` flag tells the renderer to draw an old row from its
flattened columns — which is all the data those rows ever had — while
new rows can additionally render parts, reasoning markers, and tool
interleaving from the tree. The `NOT IN` clause makes backfill
idempotent from the view's perspective: a backfilled conversation's
rows keep their original ids in the new table, so the archive copies
drop out of the view automatically (both pk-indexed; the subquery is
cheap).

Search: the archive keeps its FTS index (renamed alongside the table),
the new table gets its own, and `llm logs -q` queries both and merges —
two index probes, not a compatibility fork.

### The chain view

Reads walk parent pointers with a recursive CTE. To keep that out of
casual queries, the migration ships a view reconstructing every new-era
response's full chain with three scopes — `history` (inherited from
prior turns), `input` (this turn's new input), `output`:

```sql
CREATE VIEW response_chains AS
WITH RECURSIVE chain(response_id, node_id, message_id, depth, first_input_depth, input_depth) AS (
  SELECT r.id, n.id, n.message_id, n.depth,
         coalesce((SELECT depth FROM nodes WHERE id = r.first_input_node_id), 1e9),
         coalesce((SELECT depth FROM nodes WHERE id = r.input_node_id), -1)
  FROM responses r JOIN nodes n ON n.id = coalesce(r.output_node_id, r.input_node_id)
  UNION ALL
  SELECT chain.response_id, n.id, n.message_id, n.depth,
         chain.first_input_depth, chain.input_depth
  FROM chain JOIN nodes n ON n.id = (SELECT parent_id FROM nodes WHERE id = chain.node_id)
)
SELECT response_id, node_id, message_id, depth,
       CASE WHEN depth > input_depth THEN 'output'
            WHEN depth >= first_input_depth THEN 'input'
            ELSE 'history' END AS scope
FROM chain;
```

(Ordering: `depth` ascending. Exact SQL to be settled during
implementation; the shape is what matters here.)

Tool calls and results then fall out as trivial filters:

```sql
CREATE VIEW response_tool_calls AS
  SELECT c.response_id, p.name, p.arguments, p.tool_call_id, p.server_executed
  FROM response_chains c JOIN parts p ON p.message_id = c.message_id
  WHERE c.scope = 'output' AND p.type = 'tool_call';

CREATE VIEW response_tool_results AS
  SELECT c.response_id, p.name, p.output, p.tool_call_id, p.exception, p.instance_id
  FROM response_chains c JOIN parts p ON p.message_id = c.message_id
  WHERE c.scope = 'input' AND p.type = 'tool_result';
```

## The append-only invariant

The tree assumes each turn **extends** the previous leaf. This holds
today by construction: `_BaseConversation._build_full_chain` builds the
next prompt as `last.prompt.messages + last._messages_now() + new
input`, strictly appending. The design makes that a stated invariant
with a test, because anything that rewrites earlier history (context
condensing, retroactive redaction à la #1396) would no longer match the
stored path and would fork the tree on every subsequent turn — correct,
never lossy, but storage-costly. If history rewriting becomes a feature,
it should be modeled as an explicit branch with provenance, not a
silent mutation.

When a caller passes an arbitrary explicit `messages=` list that does
not extend any stored chain, the write path degrades gracefully:
`ensure_node` walking from the root finds the longest existing prefix
and materializes only the divergent suffix as a new branch. Worst case
(no shared prefix) it writes the whole path once.

## Write path (`log_to_db`)

1. Insert attachments first (`replace=True`, content-addressed — as now).
2. `ensure_message(db, message)` for each message: compute the hash; if
   new, insert the `messages` row plus its `parts` (and
   `part_attachments`) in the same transaction; if the hash exists, skip.
   Mirrors `ensure_fragment` / `ensure_tool`.
3. Establish the input leaf:
   - **Conversation flow** (the common case): the previous response's
     `output_node_id` is a known leaf and, under the append-only
     invariant, `prompt.messages` extends it — so only the suffix
     beyond that leaf's depth is walked through `ensure_node`. O(1)
     lookups and rows. The first new node is `first_input_node_id`.
   - **Explicit `messages=` / no prior leaf** (includes the stateless
     server case): walk the full list from the root via `ensure_node`.
     O(chain) indexed lookups — unavoidable when the client re-sends
     history — but O(new content) rows.
4. Append output messages as nodes from the input leaf; record
   `input_node_id` / `first_input_node_id` / `output_node_id` on the
   new `responses` row.
5. Write the `responses` row including the derived text columns, the
   `conversations` row (`ignore=True`), `response_fragments`,
   `response_tools`, schemas — same logic as today, new table names.

Legacy shapes are never written.

## Read path (`from_row` / `load_conversation`)

The hot path is single-era:

- recursive walk from `input_node_id` to root, reversed → input
  messages → `Prompt(messages=input, system=row["system"], options=...)`
  — the explicit-messages path, already authoritative under the
  `Prompt.messages` invariant
- the segment from `input_node_id` (exclusive) to `output_node_id`
  (inclusive) → `response._loaded_messages`, with `_chunks` rebuilt from
  text parts — exactly what `_response_from_dict` does today

`load_conversation` adds one step before reading: if the requested
conversation has rows in `responses_archive` whose ids are not yet in
`responses`, run the **lazy backfill** for that conversation — convert
its archived rows (via the quarantined legacy reconstruction) through
the standard write path, preserving response ids — then proceed down
the normal single path. Idempotent by construction (content hashes +
node dedupe + preserved ids), bounded to one conversation, and
invisible to the user beyond a brief first-touch delay. The
chain-rebuilding patch in `load_conversation` is deleted; for archived
conversations the backfill performs that reconstruction exactly once,
after which the stored path *is* the chain.

`llm logs list` reads `all_responses` (both eras); rich part-level
rendering applies to new-era rows.

## The stateless server case

This design exists in large part so an OpenAI-compatible chat
completions endpoint can log every request without storing the re-sent
history again each turn:

- **Per-turn cost:** hash each incoming message (O(chain) CPU, forced
  by the protocol), walk `(parent_id, message_id)` lookups down the
  tree, write nodes only for what's new. Turn 50 of a served
  conversation writes the same handful of rows as turn 2.
- **Conversation identification comes free:** the history *is* the
  address. The longest-prefix walk lands on the leaf to extend — no
  conversation id in the request, no trust in client-supplied identity.
- **The echo problem becomes structure:** when a client echoes a
  plain-text copy of a rich assistant message (chat completions can't
  carry reasoning parts or signatures), the walk mismatches at that
  node and branches — the degraded echo becomes a *sibling* of the rich
  original under the same parent. The relationship is recorded rather
  than lost, and a server that wants to can deliberately substitute its
  own richer node at that position to restore signatures the wire
  format dropped.

## Round-trip guarantee

The contract is stated in terms of the canonical wire format:

```
rows_to_message(message_to_rows(m)).to_dict() == m.to_dict()
```

for every Part type with every optional field present and absent, and at
the response level: path-to-messages over the stored nodes reproduces
`prompt.messages` and `_messages_now()` exactly. Tests:

1. **Property/parametrized part round trip** — all five part types ×
   optional-field combinations (`provider_metadata`, `redacted`,
   `server_executed`, `exception`, attachments by url/path/content).
2. **Full response round trip** — build a Response covering interleaved
   text/reasoning/tool-call parts and multi-message output;
   `log_to_db()` then `from_row()`; assert `to_dict()` equality
   (including `usage` and `datetime_utc`).
3. **Linear growth** — log a 3-turn conversation; assert each distinct
   message has exactly one `messages` row, each position one node, and
   turn N writes only turn-N nodes.
4. **Fork semantics** — replay a chain that diverges at an interior
   message; assert a sibling branch, no duplicated prefix nodes, and
   both leaves round-trip independently.
5. **Append-only invariant** — `_build_full_chain` output always
   extends the previous `output_node_id` path.
6. **Hash stability** — golden hashes for fixed messages, so an
   accidental change to canonical serialization fails loudly rather than
   silently forking the dedupe space.
7. **Union view** — fixture DB with legacy rows; after migration,
   `llm logs` lists old and new rows interleaved in chronological
   order; `llm logs -q` finds text in both eras.
8. **Lazy backfill** — `llm -c` against an archived conversation
   converts it once, continues correctly, and the archive copies drop
   out of `all_responses`; a second continuation performs no
   conversion; `llm logs backfill` over the whole database is a no-op
   for already-converted conversations.

## Migration and rollout

`m023_messages_tables`, in order:

1. `ALTER TABLE responses RENAME TO responses_archive` — metadata-only,
   instant, nothing destroyed. Drop the legacy FTS triggers
   (`responses_ai`/`_ad`/`_au` — the archive is frozen, they will never
   fire again) and rename `responses_fts` to `responses_archive_fts`
   (FTS5 renames carry their shadow tables along).
2. Create `messages`, `parts`, `part_attachments`, `nodes`, the new
   `responses`, `response_fragments`, `response_tools`, indexes, and
   the new table's FTS — all empty, all pure creates.
3. Create the `all_responses`, `response_chains`,
   `response_tool_calls`, `response_tool_results` views.

`conversations` is untouched and shared. The other legacy tables are
untouched under their existing names. Earlier migrations remain in
`migrations.py` so old databases reach a consistent legacy state before
m023 runs.

Backfill:

- **Lazy, per-conversation** — triggered by `llm -c` /
  `load_conversation` as described above. Covers the only case where
  old data must become new-shaped to be *used* rather than *viewed*.
- **`llm logs backfill`** — explicit bulk conversion for users who want
  their whole archive queryable through the tree views. Idempotent;
  shares the same quarantined conversion code, which is the only
  legacy-reading Python in the codebase.

## Example queries this unlocks

```sql
-- Old and new logs together, newest first (what llm logs reads)
SELECT id, model, prompt, response, archived
FROM all_responses ORDER BY id DESC LIMIT 20;

-- Reasoning emitted per response, with redaction markers visible
SELECT c.response_id, p."order", p.redacted, p.text
FROM response_chains c JOIN parts p ON p.message_id = c.message_id
WHERE c.scope = 'output' AND p.type = 'reasoning';

-- Every response that ever saw a given attachment, and how
SELECT DISTINCT c.response_id, c.scope
FROM response_chains c JOIN parts p ON p.message_id = c.message_id
WHERE p.attachment_id = :attachment_id;

-- Tool calls with their matching results, across the turn boundary
SELECT c.name, c.arguments, r.output, r.exception
FROM response_tool_calls c
LEFT JOIN response_tool_results r USING (tool_call_id);

-- Branch points: positions where a conversation forked
SELECT parent_id, count(*) AS branches
FROM nodes GROUP BY parent_id HAVING count(*) > 1;
```

## Alternatives considered

**Flat per-response link table** (revision 1): a
`response_messages(response_id, message_id, scope, "order")` table
recording the full chain per response. Same content-addressed value
layer, simpler reads (one indexed join, no recursion). Rejected because
it writes O(chain) link rows per turn — quadratic over a conversation
and exactly wrong for the stateless server case — and because it cannot
represent branching at all; it was encoding paths the expensive way.

**In-place compatible evolution** (revision 2): reuse the `responses`
table, keep legacy columns alive through `add_column`, maintain a dual
read path and compatibility views forever. Rejected: the migration
complexity, the permanent legacy branch in `from_row`, and the
contorted compat SQL all bought compatibility that the archive rename
plus union view provide more cheaply.

**Invisible-until-backfill clean break** (revision 3): new names,
legacy tables ignored entirely, explicit backfill as the only bridge.
Rejected because it makes `llm logs` stop returning pre-upgrade history
until the user intervenes — unacceptable for a personal archive.

**Response-level predecessor** (resurrect `reply_to_id` + per-turn
delta messages): simpler still, but it can't represent the echo-fork or
mid-turn branching, a regenerated turn awkwardly shares a parent
*response* rather than a parent *message*, and reconstruction
reintroduces the chain-stitching logic this redesign deletes. If the
tree is worth doing, it's worth doing at node granularity.

**Verbatim JSON blobs** (store `Response.to_dict()` per response):
trivially round-trippable, zero queryability, quadratic storage. The
`prompt_json` / `response_json` columns already cover the
audit-the-raw-payload need.

## Open questions

1. **View naming** — `all_responses` here; alternatives include
   `responses_combined` or resurrecting `logs` (risky: pre-m009
   databases may still contain a real `logs` table that m009 declined
   to drop). Same low-stakes question for `parts` vs `message_parts`,
   `nodes` vs `message_nodes`.
2. **Eager option** — should `llm logs backfill` be suggested (or
   offered interactively) after migration for small databases, so the
   tree views cover the whole archive immediately? Lazy backfill makes
   this optional rather than load-bearing.
3. **FTS over parts** — should `parts.text` / `parts.output` get their
   own FTS table so `llm logs -q` can find text inside tool output and
   reasoning? Proposed as a follow-up, not part of this migration.
4. **`prompt_json` / `response_json`** — the raw provider payloads stay
   for audit/debugging, but with the structured shape stored faithfully
   they could become opt-in (`--log-raw`?) in a future release to cut
   database size.
5. **Branch garbage collection** — abandoned branches (echo forks,
   regenerated turns) accumulate; nodes are cheap, but a future
   `llm logs prune` would need delete-ordering rules for shared
   ancestry. Out of scope for the migration.
