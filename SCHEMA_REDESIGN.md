# Design proposal: persisting Messages and Parts to SQLite

Status: proposal, revision 2 (0.32 alpha series)

This is the final stage before a non-alpha release: persisting the new
Message/Part shape (`llm/parts.py`, `llm/serialization.py`) to a redesigned
set of database tables, such that a logged response is fully
round-trippable — `log_to_db()` followed by `from_row()` must reproduce
the same structure that `Response.to_dict()` / `Response.from_dict()`
round-trips today.

Revision 2 replaces the flat per-response link table from revision 1
with a **node tree**: positions in a conversation point at their parent,
a chain is a root-to-leaf path, and a response records the leaf it sent
and the leaf it produced. See "Alternatives considered" for the
comparison.

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
4. **Queryable in plain SQLite/Datasette.** Typed columns for the common
   questions ("all tool calls", "all reasoning", "which responses used
   this image"), JSON1-queryable text columns for the open-ended parts.
5. **Keep what works.** Content-addressing (attachments/fragments are
   sha256, schemas blake2b, tools hashed), sqlite-utils migrations, the
   `responses` table as the unit of `llm logs`, FTS on prompt/response,
   and the fragments/tools/schemas tables — all unchanged.

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

## New tables

Five new tables, created by migration `m023_messages_tables`:

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
counting recursion steps, and so input/output scopes can be separated
with a comparison (see the view below).

### Changes to `responses` — kept, two new columns

| new column       | type | notes                                          |
|------------------|------|------------------------------------------------|
| `input_node_id`  | TEXT FK → nodes | leaf of `prompt.messages` as sent; `NULL` for an empty chain |
| `output_node_id` | TEXT FK → nodes | leaf after appending `_messages_now()`; `NULL` if no output (error/cancelled) |

The path from root to `input_node_id` *is* `prompt.messages`. The path
segment from (exclusive) `input_node_id` to (inclusive) `output_node_id`
is the response's output messages. The next turn in the conversation
extends `output_node_id`. A regenerated turn extends the same parent —
a sibling branch, visible in the data instead of impossible to express.

`id` (ULID), `model`, `resolved_model`, `conversation_id`,
`options_json`, `schema_id`, `prompt_json`, `response_json`,
`duration_ms`, `datetime_utc`, `input_tokens`, `output_tokens`,
`token_details` all keep their current roles.

`prompt`, `system`, `response`, `reasoning` remain as **derived
convenience columns** — written from the same data that produces the
node/message rows, so `llm logs`, FTS (`responses_fts` on
prompt/response), and existing Datasette dashboards keep working
untouched. They are documented as projections; the node tree is the
source of truth.

### The chain view

Reads walk parent pointers with a recursive CTE. To keep that out of
casual queries, the migration ships a view that reconstructs every
response's full chain with scopes:

```sql
CREATE VIEW v_response_chains AS
WITH RECURSIVE chain(response_id, node_id, message_id, depth, input_depth) AS (
  SELECT r.id, n.id, n.message_id, n.depth,
         coalesce((SELECT depth FROM nodes WHERE id = r.input_node_id), -1)
  FROM responses r JOIN nodes n ON n.id = coalesce(r.output_node_id, r.input_node_id)
  UNION ALL
  SELECT chain.response_id, n.id, n.message_id, n.depth, chain.input_depth
  FROM chain JOIN nodes n ON n.id = (SELECT parent_id FROM nodes WHERE id = chain.node_id)
)
SELECT response_id, node_id, message_id, depth,
       CASE WHEN depth > input_depth THEN 'output' ELSE 'input' END AS scope
FROM chain;
```

(Ordering: `depth` ascending. Exact SQL to be settled during
implementation; the shape is what matters here.)

## Superseded and unchanged tables

**Superseded (kept for legacy rows, no longer written):** `tool_calls`,
`tool_results`, `tool_results_attachments`, `prompt_attachments` are
replaced by `parts`. Following the m009/m010 precedent the migration
does not drop or rewrite them — old rows remain readable through the
existing `from_row` fallback. Compat views select from the new shape:

```sql
CREATE VIEW v_tool_calls AS
  SELECT c.response_id, p.name, p.arguments, p.tool_call_id, p.server_executed
  FROM v_response_chains c
  JOIN parts p ON p.message_id = c.message_id
  WHERE c.scope = 'output' AND p.type = 'tool_call';

CREATE VIEW v_tool_results AS
  SELECT c.response_id, p.name, p.output, p.tool_call_id, p.exception, p.instance_id
  FROM v_response_chains c
  JOIN parts p ON p.message_id = c.message_id
  WHERE c.scope = 'input' AND c.depth > (
    SELECT coalesce(max(depth), -1) FROM v_response_chains prev
    JOIN responses pr ON pr.id = prev.response_id
    WHERE pr.conversation_id = (SELECT conversation_id FROM responses WHERE id = c.response_id)
      AND pr.id < c.response_id
  ) AND p.type = 'tool_result';
```

(Tool *calls* are model output; tool *results* arrive as new input on
the next response — scope plus "newer than the previous leaf" encodes
that. The second view's correlation is the clumsiest SQL in this
proposal; if it stays clumsy in practice, a `first_input_node_id`
column on responses marking where its *new* input begins is the
escape hatch.)

**Unchanged:**

- `conversations` — unchanged. Conversation membership lives on
  `responses.conversation_id`; the tree itself is conversation-agnostic,
  which is what lets identical prefixes share storage across
  conversations.
- `fragments`, `fragment_aliases`, `prompt_fragments`, `system_fragments`
  — unchanged. Fragments are a text-expansion feature that operates
  *before* messages are built, keyed on `response_id` for provenance.
- `tools`, `tool_responses`, `tool_instances` — unchanged. Tool
  *definitions* offered to a prompt are not part of the message chain.
- `schemas`, `attachments` — unchanged.
- Embeddings tables — out of scope.

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
(no shared prefix) it writes the whole path once — which is what every
turn cost under a flat link-table design.

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
     lookups and rows.
   - **Explicit `messages=` / no prior leaf** (includes the stateless
     server case): walk the full list from the root via `ensure_node`.
     O(chain) indexed lookups — unavoidable when the client re-sends
     history — but O(new content) rows.
4. Append output messages as nodes from the input leaf; record
   `input_node_id` / `output_node_id` on the `responses` row.
5. Write the `responses` row including the derived text columns
   (`prompt`, `system`, `response`, `reasoning`) exactly as today.
6. Stop writing `tool_calls` / `tool_results` / `prompt_attachments` /
   `tool_results_attachments`.

Fragments, tools, schemas, `condense_json` replacements: unchanged.

## Read path (`from_row` / `load_conversation`)

If the response has `input_node_id` or `output_node_id` (new-style row):

- recursive walk from `input_node_id` to root, reversed → input
  messages → `Prompt(messages=input, system=row["system"], options=...)`
  — the explicit-messages path, already authoritative under the
  `Prompt.messages` invariant
- the segment from `input_node_id` (exclusive) to `output_node_id`
  (inclusive) → `response._loaded_messages`, with `_chunks` rebuilt from
  text parts — exactly what `_response_from_dict` does today

Otherwise fall back to the current legacy reconstruction. This lets
`load_conversation` delete its chain-rebuilding patch for new rows: the
stored path *is* the chain, with signatures and redacted markers intact,
which is what makes `llm -c` onto a reasoning model and chain resume
from pending tool calls actually correct.

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
7. **Legacy fallback** — fixture DB with pre-m023 rows still loads, and
   `llm -c` still works against it.

## Migration and rollout

- `m023_messages_tables`: create `messages`, `parts`,
  `part_attachments`, `nodes`, the indexes, the views, and the two
  `responses` columns. No automatic rewriting of historical data (m009
  precedent: never destroy or churn user data in a migration).
- Optional backfill as an explicit command — `llm logs backfill-messages`
  — which runs the legacy `from_row` reconstruction per response in
  conversation order and feeds it through the standard write path.
  Idempotent by construction (content hashes + node dedupe). Old rows
  it can't fully reconstruct (they never stored metadata) backfill as
  faithfully as the legacy columns allow, which is no worse than
  reading them today.

## Example queries this unlocks

```sql
-- Reasoning emitted per response, with redaction markers visible
SELECT c.response_id, p."order", p.redacted, p.text
FROM v_response_chains c
JOIN parts p ON p.message_id = c.message_id
WHERE c.scope = 'output' AND p.type = 'reasoning';

-- Every response that ever saw a given attachment, input or output
SELECT DISTINCT c.response_id, c.scope
FROM v_response_chains c
JOIN parts p ON p.message_id = c.message_id
WHERE p.attachment_id = :attachment_id;

-- Tool calls with their matching results, across the turn boundary
SELECT c.name, c.arguments, r.output, r.exception
FROM v_tool_calls c LEFT JOIN v_tool_results r USING (tool_call_id);

-- Branch points: positions where a conversation forked
SELECT parent_id, count(*) AS branches
FROM nodes GROUP BY parent_id HAVING count(*) > 1;
```

## Alternatives considered

**Flat per-response link table** (revision 1 of this proposal): a
`response_messages(response_id, message_id, scope, "order")` table
recording the full chain per response. Same content-addressed value
layer, simpler reads (one indexed join, no recursion). Rejected because
it writes O(chain) link rows per turn — quadratic over a conversation
and exactly wrong for the stateless server case — and because it cannot
represent branching at all; it was encoding paths the expensive way.

**Response-level predecessor** (resurrect `reply_to_id` + per-turn
delta messages): simpler still, but it can't represent the echo-fork or
mid-turn branching, a regenerated turn awkwardly shares a parent
*response* rather than a parent *message*, and reconstruction reintroduces
the chain-stitching logic this redesign is trying to delete. If the
tree is worth doing, it's worth doing at node granularity.

**Verbatim JSON blobs** (store `Response.to_dict()` per response):
trivially round-trippable, zero queryability, quadratic storage. The
`prompt_json` / `response_json` columns already cover the
audit-the-raw-payload need.

## Open questions

1. **Table naming** — `parts` is short and matches `llm/parts.py`;
   `message_parts` is more self-describing in a shared logs.db. Same
   question for `nodes` vs `message_nodes`.
2. **FTS over parts** — should `parts.text` / `parts.output` get their
   own FTS table so `llm logs -q` can find text inside tool output and
   reasoning? Proposed as a follow-up, not part of this migration.
3. **`prompt_json` / `response_json`** — the raw provider payloads stay
   for audit/debugging, but with the structured shape stored faithfully
   they could become opt-in (`--log-raw`?) in a future release to cut
   database size.
4. **Branch garbage collection** — abandoned branches (echo forks,
   regenerated turns) accumulate; nodes are cheap, but a future
   `llm logs prune` would need delete-ordering rules for shared
   ancestry. Out of scope for the migration.
5. **`v_tool_results` correlation** — if the "new input since the
   previous leaf" SQL proves too clumsy, add a
   `responses.first_input_node_id` column marking where the turn's new
   input begins.
