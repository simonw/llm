# llm-upgrade-logs — specification

Specification for a separate plugin, **`llm-upgrade-logs`**, that ports
logs recorded by older versions of LLM (the frozen `responses` /
`tool_calls` / `tool_results` family) into the current structured
message store (`messages`, `message_nodes`, `responses_v2` and its link
tables). This document is the contract the plugin should be built and
tested against.

## Purpose

LLM core no longer reads or writes the pre-message-store tables. A
database created by an older version keeps every byte of its old data —
core never modifies or deletes those tables — but `llm logs`, `llm -c`
and `llm logs -q` only see rows in the current format. This plugin
closes that gap by converting old rows into new rows, once, on demand.

All knowledge of the legacy schema lives in this plugin. Core's only
concessions are the hint in `llm logs status` (it counts rows in
`responses` without understanding them) and the stable
`llm.message_store` API the plugin writes through.

## Principles

1. **The old tables are never modified.** The port only INSERTs into
   current-format tables. The legacy tables remain the immutable source
   of truth; if a future version of the converter is smarter, the port
   can be re-run from the originals.
2. **Idempotent and resumable.** A response whose id already exists in
   `responses_v2` is skipped. Interrupting and re-running the command
   is always safe. Content-addressing makes re-inserted messages free.
3. **IDs are preserved.** `responses_v2.id` is the legacy
   `responses.id`; conversation ids are reused. Ordering (ULIDs),
   `llm logs --cid`, and `llm -c` continuation across the upgrade
   boundary all work because of this. Condensed `{"$": "r:<id>"}`
   references inside legacy `response_json` values remain resolvable
   for the same reason.
4. **Lossy-but-honest synthesis.** Old rows never recorded full part
   structure. The converter synthesizes the best structured form the
   data supports (see mapping below) and must not invent anything else.
   `prompt_json` is *not* ported — it stays available in the archive
   for anyone who wants the original provider wire format.
5. **Defensive reads.** Old databases may sit at any migration level
   (for example, pre-tools versions have no `tool_calls` table; very
   old databases may have a `logs` table this plugin does not attempt
   to handle). Read only the tables and columns that exist; never run
   legacy migrations against the user's database.

## Commands

Registered via the existing `register_commands` plugin hook — no new
core hooks are required.

### `llm upgrade-logs [PATH]`

Ports all un-ported legacy responses in the logs database (default:
`llm logs path`; `PATH` overrides, mirroring `-d/--database` elsewhere).

Options:

- `--dry-run` — report what would be ported (row counts, detected
  legacy migration level, any rows that would be skipped and why)
  without writing.
- `--batch-size N` — commit in batches (default 100) so progress
  survives interruption; show a progress bar for large databases.

Output on completion: number of responses ported, number skipped as
already ported, number of conversations touched, and before/after
database file size.

### `llm upgrade-logs status [PATH]`

Reports: legacy responses present, how many are already ported, and
whether the database predates tables the converter reads (tools,
fragments, attachments) so the user understands what the port can and
cannot recover.

### `llm upgrade-logs drop-legacy [PATH]` (phase two, optional)

Deletes the frozen legacy tables after verifying every legacy response
id exists in `responses_v2`. Requires an interactive `yes I am sure`
confirmation and prints a suggestion to run `llm logs backup` first.
Ship this only once the converter has been stable for a while.

## Conversion mapping

For each legacy `responses` row, in `id` order, grouped by
`conversation_id` (processing a conversation's rows oldest-first is
**required** — the chain construction below depends on it):

### Message synthesis

Build the turn's input messages the same way `Prompt.messages`
synthesizes them from legacy fields, appended to the running
conversation chain:

1. Start from `previous_chain` — the full chain (input + output) of the
   previous response in the same conversation, or `[]` for the first.
2. `system` role message: the legacy `system` column concatenated with
   any system fragments (join `system_fragments` → `fragments` on the
   old side, in `"order"`), only when it differs from the previous
   turn's effective system prompt — matching `_build_full_chain`'s
   system-dedup rule.
3. `tool` role message: one `ToolResultPart` per legacy `tool_results`
   row for this response (in `id` order) with `name`, `output`,
   `tool_call_id`, `exception`, and attachments resolved via
   `tool_results_attachments` into `Attachment` objects (the attachment
   rows already exist in the shared `attachments` table; reference
   them, do not copy).
4. `user` role message: a `TextPart` holding prompt fragments + the
   `prompt` column concatenated (fragments first, `"order"` respected,
   joined with newlines — the `Prompt.prompt` property rule), plus one
   `AttachmentPart` per `prompt_attachments` row in `"order"`.

Output messages, one `assistant` role message containing, in order:

1. A `ReasoningPart(text=reasoning)` if the `reasoning` column is
   non-empty (this column exists from migration `m022` onward).
2. A `TextPart(text=response)` if the `response` column is non-empty.
3. One `ToolCallPart` per legacy `tool_calls` row (in `id` order) with
   `name`, JSON-decoded `arguments`, and `tool_call_id`.

Interleaving is not recoverable from legacy rows; this fixed order is
the documented convention. Store with:

```python
input_node_id = llm.message_store.store_messages(db, input_chain)
output_node_id = llm.message_store.store_messages(
    db, output_messages, parent_node_id=input_node_id
)
```

Because consecutive turns extend the same chain, shared prefixes
deduplicate exactly as they do for natively logged conversations.

### responses_v2 row

Copy directly: `id`, `model`, `resolved_model` (when the column
exists), `prompt`, `system`, `options_json`, `response`, `reasoning`
(when present), `response_json`, `conversation_id`, `duration_ms`,
`datetime_utc`, `input_tokens`, `output_tokens`, `token_details`,
`schema_id`. Set `input_node_id` / `output_node_id` from the stored
chains. Do not port `prompt_json`. The insert populates
`responses_v2_fts` automatically via its triggers.

### Link and index tables

- `prompt_fragments` / `system_fragments` rows → `response_fragments`
  rows with `fragment_type` `'prompt'` / `'system'`, preserving
  `"order"`.
- `tool_responses` rows → `response_tools` rows.
- `prompt_attachments` rows → `response_attachments` rows, preserving
  `"order"`.
- `tool_results` rows → `tool_uses` rows (`name`, `tool_id`,
  `tool_call_id`). When a legacy row has `instance_id`, copy the
  referenced `tool_instances` row into `toolbox_instances` (dedupe by
  `(plugin, name, arguments)`, cache the mapping for the run) and set
  `tool_uses.instance_id` accordingly. Note the legacy writer had a
  loop-variable bug that could record the wrong toolbox `name`/`plugin`
  on `tool_instances` rows; port the values as stored — do not attempt
  to repair them.
- `conversations` and `schemas` rows are shared-catalog and already
  correct; the port never needs to touch them.

### Edge cases

- **Missing tables** (database predates the relevant migration): treat
  as empty — a pre-`m017` database simply has no tool traffic to port.
- **Null columns**: `prompt`, `system`, `response`, `reasoning` may all
  be NULL/empty; synthesize only the parts that have content. A
  response with no content at all still gets a `responses_v2` row with
  `output_node_id == input_node_id`.
- **Legacy `tool_calls.tool_call_id` may be NULL** (pre-0.32a3
  providers that supplied none). Port the NULL as-is; do not synthesize
  `tc_` ids, since matching results by invented ids would be a lie.
  Corresponding `tool_uses` rows keep the NULL too.
- **Duplicate conversation processing order**: rows within a
  conversation must be processed strictly in `id` order even when the
  port is resumed — if any row of a conversation is already ported,
  rebuild `previous_chain` by loading the ported turn via
  `llm.message_store.load_turn` rather than re-synthesizing it.
- **The `logs` table** from pre-0.3 versions of LLM is out of scope for
  the first release; `upgrade-logs status` should mention its presence
  if detected.

## Testing strategy

- Golden databases: build fixture `logs.db` files by checking out old
  LLM releases (0.26, 0.31, 0.32 alphas) in CI or vendoring pre-built
  fixtures, logging a scripted set of prompts (text, system prompts,
  fragments, attachments, tools with results and exceptions,
  multi-turn conversations, schemas), then running the port.
- Parity check: for a conversation logged natively by current LLM and
  the same conversation ported from a legacy fixture, `llm logs -n 0`
  output must be identical apart from ids and timestamps, and
  `llm -c` continuation must produce the same `prompt.messages` chain.
- Idempotency: running `llm upgrade-logs` twice must leave identical
  table counts and content hashes.
- Immutability: a byte-for-byte comparison (`PRAGMA integrity_check`
  plus a hash of each legacy table's rows) before and after the port
  must show the legacy tables untouched.

## Packaging notes

- Plugin name `llm-upgrade-logs`, module `llm_upgrade_logs.py`,
  registered via the `llm` entry point group like other plugins.
- Depends on `llm>=` the first release containing `responses_v2` and
  the `llm.message_store` API, and on `sqlite-utils`.
- The legacy-schema knowledge (table DDL expectations at each migration
  level) should live in one documented module so future formats can
  reuse the pattern.
