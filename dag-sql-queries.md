# DAG SQL queries

Reconstructing what happened from the DAG tables. Each query is
written against the schema from `plans/dag-schema.md`:

- `messages(id, parent_id, content_hash, role, provider_metadata_json, created_at)` —
  immutable, parent-linked nodes. The chain root points at a
  self-referencing sentinel row with `id = 'root'`.
- `message_parts(id, message_id, order, part_type, content, content_json, tool_call_id, server_executed)` —
  the content of each message, one row per part in order.
- `calls(id, conversation_id, head_input_message_id, head_output_message_id, model, resolved_model, started_at, duration_ms, input_tokens, output_tokens, token_details_json, error)` —
  one row per LLM call. `head_input_message_id` is the last user-side
  message the model saw; `head_output_message_id` is the last
  assistant-side message it produced. Walking `parent_id` from the
  output head back to (but not past) the input head gives the call's
  new output; walking from the input head back to `'root'` gives the
  full prior context.
- `conversations(id, name, model, head_message_id)` —
  `head_message_id` advances each saved turn.

All examples assume SQLite and use the recursive CTE pattern SQLite
supports natively. Run from any SQLite client pointed at the DB
(default `~/Library/Application Support/io.datasette.llm/dag.db` on
macOS in this branch).

## 1. Walk a conversation from its head

Given a `conversations.id`, reconstruct the full message sequence:

```sql
WITH RECURSIVE chain(id, parent_id, role, depth) AS (
  SELECT
    m.id,
    m.parent_id,
    m.role,
    0
  FROM
    messages m
    JOIN conversations c ON c.head_message_id = m.id
  WHERE
    c.id = :conversation_id
  UNION ALL
  SELECT
    m.id,
    m.parent_id,
    m.role,
    chain.depth + 1
  FROM
    messages m
    JOIN chain ON chain.parent_id = m.id
  WHERE
    m.id != 'root'
)
SELECT
  (
    SELECT
      MAX(depth)
    FROM
      chain
  ) - chain.depth AS turn,
  chain.role,
  mp.part_type,
  CASE
    mp.part_type
    WHEN 'text' THEN mp.content
    WHEN 'reasoning' THEN '[reasoning] ' || mp.content
    WHEN 'tool_call' THEN '→ ' || json_extract(mp.content_json, '$.name') || '(' || COALESCE(
      json_extract(mp.content_json, '$.arguments'),
      '{}'
    ) || ')'
    WHEN 'tool_result' THEN '← ' || substr(mp.content, 1, 200)
    WHEN 'attachment' THEN '[attachment: ' || COALESCE(json_extract(mp.content_json, '$.type'), '?') || ']'
    ELSE mp.part_type
  END AS text
FROM
  chain
  LEFT JOIN message_parts mp ON mp.message_id = chain.id
ORDER BY
  turn,
  mp."order";
```

`depth DESC` reverses the walk so the oldest message comes first.
Drop the `m.id != 'root'` clause if you want to see the sentinel.

## 2. Show a conversation with the actual text

Same walk, joined to `message_parts` to surface content. One row
per part:

```sql
WITH RECURSIVE chain(id, parent_id, role, depth) AS (
  SELECT m.id, m.parent_id, m.role, 0
    FROM messages m
    JOIN conversations c ON c.head_message_id = m.id
   WHERE c.id = :conversation_id
  UNION ALL
  SELECT m.id, m.parent_id, m.role, chain.depth + 1
    FROM messages m
    JOIN chain ON chain.parent_id = m.id
   WHERE m.id != 'root'
)
SELECT
  chain.depth,
  chain.role,
  mp.part_type,
  mp."order",
  COALESCE(mp.content, mp.content_json) AS preview
FROM chain
LEFT JOIN message_parts mp ON mp.message_id = chain.id
ORDER BY chain.depth DESC, mp."order";
```

Each message can have multiple parts (a `tool_call` part followed by
a `text` part in the same assistant turn, for instance) — `ORDER BY
depth DESC, "order"` renders them in natural reading order.

## 3. The messages produced by a specific call

A call's new output is the slice of the chain from just after its
`head_input_message_id` through its `head_output_message_id`. This
walks from the output head backwards, stopping *before* the input
head:

```sql
WITH RECURSIVE output_chain(id, parent_id, role, depth) AS (
  SELECT m.id, m.parent_id, m.role, 0
    FROM messages m
    JOIN calls c ON c.head_output_message_id = m.id
   WHERE c.id = :call_id
  UNION ALL
  SELECT m.id, m.parent_id, m.role, output_chain.depth + 1
    FROM messages m, output_chain, calls c
   WHERE c.id = :call_id
     AND output_chain.parent_id = m.id
     AND output_chain.parent_id != c.head_input_message_id
)
SELECT depth, role, id FROM output_chain ORDER BY depth DESC;
```

If `head_output_message_id = head_input_message_id` the call produced
no new messages (error / refusal) — the query returns a single row
which you can filter out application-side.

## 4. List calls for a conversation with token usage

Token columns live only on `calls`. Conversations still show as rows
in the `conversations` table:

```sql
SELECT
  c.id,
  c.started_at,
  c.model,
  c.duration_ms,
  c.input_tokens,
  c.output_tokens,
  c.input_tokens + c.output_tokens AS total_tokens,
  c.error
FROM calls c
WHERE c.conversation_id = :conversation_id
ORDER BY c.started_at;
```

## 5. Find every call that used a given tool

The model requesting a tool shows up as a `message_parts` row with
`part_type = 'tool_call'`. Join to `calls` via the output chain —
here the simplest path is "did this call's output head, or any of
its ancestors up to the input head, contain a tool_call part with
this name?".

A cheaper approximation that works when tool calls are almost always
on the output head directly:

```sql
SELECT DISTINCT c.id, c.started_at, c.model
FROM calls c
JOIN message_parts mp ON mp.message_id = c.head_output_message_id
WHERE mp.part_type = 'tool_call'
  AND json_extract(mp.content_json, '$.name') = :tool_name
ORDER BY c.started_at;
```

For the exhaustive version (tool call is anywhere in the output
chain), wrap query 3 as a subquery.

## 6. Find a conversation's branching points (forks)

A message has multiple children when two different turns continued
from it:

```sql
SELECT parent_id, COUNT(*) AS child_count
FROM messages
WHERE id != 'root'
GROUP BY parent_id
HAVING COUNT(*) > 1;
```

For each branching point, find the forked conversations:

```sql
SELECT c.id, c.name, c.head_message_id
FROM conversations c
WHERE EXISTS (
  SELECT 1 FROM messages m
  WHERE m.id = c.head_message_id
     OR m.parent_id = c.head_message_id
);
```

To find conversations that share a common prefix with a known
conversation, walk the known chain and look for other conversations
whose `head_message_id` appears anywhere in it.

## 7. Content-address lookup (has this message been seen?)

Every message is identified by `(parent_id, content_hash)`. To ask
"does a chain rooted at system-prompt-X followed by user-message-Y
already exist?", chain lookups by hash:

```sql
-- 1) Find a root message with content_hash = :h_system
SELECT id FROM messages
 WHERE parent_id = 'root' AND content_hash = :h_system;

-- 2) Given that id, find its child with content_hash = :h_user
SELECT id FROM messages
 WHERE parent_id = :system_id AND content_hash = :h_user;
```

Chain dedup and stateless-API continuation are this query in a loop
— see `MessageStore.find_longest_existing_prefix` in
`llm/storage.py`.

## 8. Storage savings from shared prefixes

Count how many calls reference each input-head message. A value > 1
means two calls shared the same input chain (a retry, a regeneration,
or a fork converging back):

```sql
SELECT
  head_input_message_id,
  COUNT(*) AS call_count
FROM calls
GROUP BY head_input_message_id
HAVING COUNT(*) > 1
ORDER BY call_count DESC;
```

To see the saving in absolute terms — messages actually stored vs.
messages naïvely required (sum of chain lengths across all calls):

```sql
WITH RECURSIVE chain_lengths(call_id, cur, steps) AS (
  SELECT c.id, c.head_output_message_id, 1
    FROM calls c
  UNION ALL
  SELECT chain_lengths.call_id, m.parent_id, chain_lengths.steps + 1
    FROM messages m, chain_lengths
   WHERE m.id = chain_lengths.cur
     AND m.id != 'root'
)
SELECT
  (SELECT COUNT(*) FROM messages WHERE id != 'root') AS messages_stored,
  (SELECT SUM(steps) FROM (
     SELECT call_id, MAX(steps) AS steps FROM chain_lengths GROUP BY call_id
  )) AS messages_naively_required;
```

## 9. Tool-call / tool-result round-trip for a call

Tool plumbing lives in `message_parts` on `tool_call_id`. Pair them:

```sql
SELECT
  call_part.tool_call_id,
  json_extract(call_part.content_json, '$.name')      AS tool_name,
  json_extract(call_part.content_json, '$.arguments') AS arguments,
  result_part.content                                  AS result_text
FROM message_parts call_part
LEFT JOIN message_parts result_part
  ON result_part.tool_call_id = call_part.tool_call_id
 AND result_part.part_type = 'tool_result'
WHERE call_part.part_type = 'tool_call';
```

`LEFT JOIN` so you see calls that never got a result (model hung up,
user bailed, tool errored in a way that wasn't logged as a part).

## 10. Raw chain dump for debugging

When something looks wrong, this prints every message in the DB with
its parent, role, and the first part's content preview:

```sql
SELECT
  m.id,
  m.parent_id,
  m.role,
  substr(m.content_hash, 1, 8) AS hash,
  mp.part_type,
  substr(COALESCE(mp.content, mp.content_json), 1, 60) AS preview
FROM messages m
LEFT JOIN message_parts mp ON mp.message_id = m.id AND mp."order" = 0
WHERE m.id != 'root'
ORDER BY m.created_at, m.id;
```

Ordering by `created_at` groups messages in insert order, which is
usually the order they happened — though dedup hits don't re-stamp,
so a resent prefix keeps its original `created_at`.
