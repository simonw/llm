# Design proposal: persisting Messages and Parts to SQLite

Status: proposal, revision 5 (0.32 alpha series)

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
- **Revision 4** kept old logs visible via a union view over a renamed
  `responses_archive` plus lazy per-conversation backfill.
- **Revision 5** (this one) goes one step further: the migration
  **eagerly converts all legacy data into the new schema**. The legacy
  tables are renamed to `*_archive` and kept untouched as a safety net,
  but after migration there is exactly one era of data: no union view,
  no dual FTS, no lazy backfill, no `archived` flag. `llm logs` and
  `llm -c` work on the full history through a single code path.

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
4. **Old logs stay visible and usable.** `llm logs` must keep returning
   pre-upgrade history and `llm -c` must keep working against
   pre-upgrade conversations, without the user running anything. The
   logs database is a personal archive; an upgrade that hides it is not
   acceptable.
5. **The migration must never brick the install.** `migrate(db)` runs
   on every llm invocation; a data-conversion migration that raises on
   one weird legacy row would make every command fail. Conversion must
   be defensive per row, with failures recorded rather than raised.
6. **Queryable in plain SQLite/Datasette.** Typed columns for the common
   questions ("all tool calls", "all reasoning", "which responses used
   this image"), JSON1-queryable text columns for the open-ended parts.
7. **Reuse the value tables.** The content-addressed stores
   (`attachments`, `fragments`, `fragment_aliases`, `schemas`, `tools`,
   `tool_instances`) keep their names and rows — old and new references
   coexist harmlessly in a content-addressed table, and attachment
   blobs (the bulk of a large logs.db) are never copied.

## The conversion rule

The migration renames `responses` to **`responses_archive`** (freeing
the natural name — a metadata-only `ALTER TABLE ... RENAME`), creates
the new tables, then **converts every archived response into the new
schema**, preserving response ids and conversation ids. The archive and
the legacy satellite tables (`tool_calls`, `tool_results`,
`prompt_attachments`, `tool_results_attachments`, `prompt_fragments`,
`system_fragments`, `tool_responses`) are kept untouched as a safety
net — nothing is ever destroyed — but no code reads them after
conversion except a repair command.

**Feasibility.** Conversion is mechanical because the synthesized
messages are exactly what `Response.from_row` + `load_conversation`
already fabricate on every `llm -c` today: per turn, a system message,
a tool message from `tool_results`, a user message from prompt text +
attachments, an assistant message from response text + `tool_calls` +
the concatenated `reasoning` column — each turn's chain extending the
previous turn's leaf, conversation by conversation in id order. Nothing
is lost that exists (old rows never stored metadata or interleaving;
they convert as sparsely as they were recorded, no worse than reading
them today). The cost is O(total logged text) — hashing and row inserts;
attachment blobs stay where they are and are only *linked* — which is
the same order of work as the m011 migration that built the FTS index
over every existing prompt and response, so llm has shipped this class
of migration before.

Three engineering requirements make it safe:

- **Plugin-free.** The converter builds `MessageDict`s directly from
  raw rows. It must not call `get_model()` or validate `Options` —
  models logged by since-uninstalled plugins must convert fine.
  `options_json` is copied verbatim.
- **Defensive per conversation.** Each conversation converts inside a
  try/except; a malformed row (broken JSON, dangling FK, half-written
  legacy data) falls back to a minimal text-only conversion, and if
  even that fails the failure is recorded in a `_conversion_errors`
  table (conversation id, response id, error) and skipped — the
  migration itself never raises (constraint 5). `llm logs backfill`
  remains as the re-runnable repair command that retries recorded
  failures after a fix.
- **Transactional and resumable.** Conversion runs in a transaction so
  an interrupt (Ctrl-C mid-migration) rolls back cleanly and re-runs
  next invocation. Idempotent by construction: preserved ids + content
  hashes + node dedupe mean re-converting is a no-op. For large tables
  a progress line goes to stderr.

What single-era steady state buys, beyond revision 4: no union view, no
`archived` rendering branch, no dual FTS query in `llm logs -q`, no
lazy-backfill trigger in `load_conversation` — the new tables simply
contain everything, and the tree views cover the whole archive from day
one. The legacy FTS artifacts (`responses_fts` and its triggers) are
dropped outright: derived indexes are not user data, and the new
table's FTS now covers the converted rows.

`conversations` is **reused, not renamed**: its shape (`id`, `name`,
`model`) is unchanged, so conversation ids stay continuous and no
conversion is needed for it at all.

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

All created by `m023_messages_tables`; all writes go here and nowhere
else.

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
`log_to_db` tracks it today (and preserved from `tool_results.instance_id`
during conversion). It does not participate in the message hash and is
not part of the round trip — same as current behavior.

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
rename. Ids are ULIDs (`Response.id`) — converted rows keep their
original ids, so `r:<id>` replacement keys in condensed JSON still
resolve and ordering by id stays chronological across the upgrade:

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
speed and FTS — defined once via
`enable_fts(["prompt", "response"], create_triggers=True)` before
conversion populates the table, so converted rows are indexed by the
triggers as they insert. The node tree is the source of truth. The
column set matches the archive's 1:1, which is what makes conversion a
column-copy plus message synthesis.

### `response_fragments`

Merges the legacy `prompt_fragments` + `system_fragments` pair into the
single relation it always was (`FRAGMENT_SQL` in `models.py` already
unions them back together with a synthesized `fragment_type` column):

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

### The chain view

Reads walk parent pointers with a recursive CTE. To keep that out of
casual queries, the migration ships a view reconstructing every
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

Tool calls and results then fall out as trivial filters — and because
the archive is fully converted, these views cover pre-upgrade history
too:

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
input`, strictly appending — and the converter builds archived
conversations the same way, turn by turn. The design makes that a
stated invariant with a test, because anything that rewrites earlier
history (context condensing, retroactive redaction à la #1396) would no
longer match the stored path and would fork the tree on every
subsequent turn — correct, never lossy, but storage-costly. If history
rewriting becomes a feature, it should be modeled as an explicit branch
with provenance, not a silent mutation.

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
   `responses` row.
5. Write the `responses` row including the derived text columns, the
   `conversations` row (`ignore=True`), `response_fragments`,
   `response_tools`, schemas — same logic as today, new table names.

The conversion in m024 is this same write path fed by synthesized
messages — one code path produces both fresh and converted data.
Legacy shapes are never written.

## Read path (`from_row` / `load_conversation`)

One path, one era, no fallback:

- recursive walk from `input_node_id` to root, reversed → input
  messages → `Prompt(messages=input, system=row["system"], options=...)`
  — the explicit-messages path, already authoritative under the
  `Prompt.messages` invariant
- the segment from `input_node_id` (exclusive) to `output_node_id`
  (inclusive) → `response._loaded_messages`, with `_chunks` rebuilt from
  text parts — exactly what `_response_from_dict` does today

`load_conversation` deletes its chain-rebuilding patch: the stored path
*is* the chain — for pre-upgrade conversations because the converter
performed that reconstruction exactly once, for new ones because
`log_to_db` stored it directly. `llm logs` reads the new `responses`
only; `llm logs -q` queries one FTS index covering all history.

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
7. **Conversion equivalence** — fixture DBs from real prior llm
   versions (tools, attachments, fragments, schemas, reasoning,
   multi-turn conversations); after migration, `llm logs` output and
   `load_conversation` results match what the legacy reader produced on
   the same fixtures before migration; ids preserved; re-running
   conversion is a no-op.
8. **Conversion never raises** — fixtures with malformed options_json,
   dangling schema_id/conversation_id, NULL response text; migration
   completes, damage is confined to `_conversion_errors`, and every
   other row converts.
9. **Conversion without plugins** — fixture logged by a model whose
   plugin is not installed converts fully.

## Migration and rollout

`m023_messages_tables`:

1. `ALTER TABLE responses RENAME TO responses_archive` — metadata-only,
   instant, nothing destroyed. Drop the legacy FTS triggers and FTS
   tables (derived indexes, not user data; their replacement covers
   everything once conversion runs).
2. Create `messages`, `parts`, `part_attachments`, `nodes`, the new
   `responses`, `response_fragments`, `response_tools`,
   `_conversion_errors`, indexes, the new FTS, and the views — all
   pure creates.

`m024_convert_legacy`:

3. For each conversation in `responses_archive` (id order), synthesize
   each turn's messages from the flattened columns and satellite
   tables — exactly the reconstruction `from_row` performs today, but
   plugin-free — and feed them through the standard write path,
   preserving response ids. Copy `prompt_fragments` +
   `system_fragments` → `response_fragments`, `tool_responses` →
   `response_tools`, link attachments in place. Transactional,
   idempotent, defensive per conversation (failures land in
   `_conversion_errors`, never raise), progress to stderr for large
   tables. Cost is O(total logged text) — the same class of one-time
   work as m011's FTS build.

`conversations` is untouched and shared. The archive tables stay,
unread, under `*_archive` and their original satellite names — a
safety net for at least one release cycle; a far-future migration (or
`llm logs prune-archive`) can offer to drop them.

`llm logs backfill` survives only as the repair command: it retries
conversations recorded in `_conversion_errors` (after a bugfix
release) and is a no-op otherwise.

## Example queries this unlocks

```sql
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

All of these span the user's entire history, pre- and post-upgrade.

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
read path and compatibility views forever. Rejected: permanent
complexity buying what a one-time conversion provides more honestly.

**Invisible-until-backfill clean break** (revision 3): new names,
legacy tables ignored, explicit backfill as the only bridge. Rejected
because it makes `llm logs` stop returning pre-upgrade history until
the user intervenes — unacceptable for a personal archive.

**Union view + lazy backfill** (revision 4): instant migration, old
rows visible through an `all_responses` view, conversations converted
on first `llm -c` touch. Strictly safer at upgrade time than eager
conversion and the designated **fallback if benchmarking the converter
on large real-world databases shows unacceptable migration times** —
but it leaves two eras of data in the steady state: a union view, dual
FTS queries, an `archived` rendering branch, and tree views that only
cover post-upgrade history. Eager conversion was chosen because the
upgrade moment is one-time and bounded while the dual-era complexity
is forever.

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

## Implementation notes

The implementation (llm/storage.py, llm/conversion.py, migrations
m023-m025) follows this design with three deviations:

1. **Migration split.** Three migrations instead of two:
   `m023_parts_tables` (messages/parts/part_attachments/nodes, purely
   additive), `m024_new_responses` (the cutover: archive rename, new
   responses table, views), `m025_convert_legacy` (the converter).
2. **`first_input_node_id` semantics.** On the live write path it is
   the first *newly created* node in the input walk — NULL when an
   identical chain was replayed (no new input). The converter, which
   knows the turn boundary exactly, records the first node of the new
   input segment whether or not it was deduplicated.
3. **Extra view.** `response_attachments` (input-scope attachment
   parts) ships alongside the three views described here, replacing the
   CLI's join against the legacy `prompt_attachments` table.

## Open questions

1. **Converter benchmark** — measure m024 on a large real logs.db
   (years of history, hundreds of thousands of responses) before the
   non-alpha release. If it lands in minutes-not-seconds territory on
   realistic databases, fall back to the revision 4 design (union view
   + lazy backfill), which is preserved in this document's history.
2. **Naming** — `parts` vs `message_parts`, `nodes` vs `message_nodes`
   in a logs.db users also query directly. Low stakes.
3. **FTS over parts** — should `parts.text` / `parts.output` get their
   own FTS table so `llm logs -q` can find text inside tool output and
   reasoning? Proposed as a follow-up, not part of this migration.
4. **`prompt_json` / `response_json`** — the raw provider payloads stay
   for audit/debugging (and are copied through conversion), but with
   the structured shape stored faithfully they could become opt-in
   (`--log-raw`?) in a future release to cut database size.
5. **Archive retention** — how long do the `*_archive` tables stick
   around, and does dropping them eventually warrant an interactive
   `llm logs prune-archive` rather than a migration? Nothing in this
   proposal ever drops them automatically.
6. **Branch garbage collection** — abandoned branches (echo forks,
   regenerated turns) accumulate; nodes are cheap, but a future
   `llm logs prune` would need delete-ordering rules for shared
   ancestry. Out of scope for the migration.
