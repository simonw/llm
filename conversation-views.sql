-- A readable rendering of the content-addressed message tree.
--
-- Prototype: applied directly to logs.db rather than added to
-- llm/migrations.py, so it can be reshaped without a migration.
-- Re-runnable - the view is dropped first.
--
--   select entry from conversation_tree;               -- everything
--   select entry from conversation_tree where id = 'faafcc3b';
--
-- One row per part, depth-first, so reading `entry` top to bottom
-- replays the conversation. Indentation tracks *branching*, not depth:
-- a conversation that never forks stays flush left however long it
-- runs, and each divergence steps one level in. Where a message forked,
-- each branch is headed [n/total] and its whole subtree is aligned
-- underneath, so it is always clear which reply belongs to which try.

DROP VIEW IF EXISTS conversation_tree;
DROP VIEW IF EXISTS part_text;

-- Resolves a part's text back from storage. Text that borrowed from a
-- fragment is stored as an ordered list of fragment references and
-- literals rather than a copy, so reading it means splicing the
-- fragment contents back in.
CREATE VIEW part_text AS
SELECT
    p.id AS part_id,
    coalesce(
        json_extract(p.payload, '$.text'),
        (
            SELECT group_concat(
                coalesce(
                    json_extract(piece.value, '$.literal'),
                    (SELECT f.content FROM fragments f
                      WHERE f.id = json_extract(piece.value, '$.fragment'))
                ),
                '' ORDER BY piece.key
            )
            FROM json_each(json_extract(p.payload, '$.text_ref')) piece
        )
    ) AS text
FROM parts p;

CREATE VIEW conversation_tree AS
WITH RECURSIVE
-- Where each message sits among its siblings. Computed up front
-- because window functions are not allowed in a recursive term.
sibling AS (
    SELECT
        hash,
        parent_hash,
        row_number() OVER (PARTITION BY parent_hash ORDER BY rowid) AS ord,
        count(*) OVER (PARTITION BY parent_hash) AS of
    FROM messages
),
walk(root_hash, message_hash, depth, indent, ord, of, sort_key) AS (
    SELECT m.hash, m.hash, 0, 0, 1, 1, printf('%08d', m.rowid)
    FROM messages m
    WHERE m.parent_hash IS NULL
  UNION ALL
    SELECT
        w.root_hash,
        s.hash,
        w.depth + 1,
        -- Step in only where the parent actually forked.
        w.indent + (CASE WHEN s.of > 1 THEN 1 ELSE 0 END),
        s.ord,
        s.of,
        w.sort_key || '/' || printf('%08d', m.rowid)
    FROM sibling s
    JOIN messages m ON m.hash = s.hash
    JOIN walk w ON s.parent_hash = w.message_hash
),
rendered AS (
    SELECT
        w.*,
        m.role,
        p.position,
        p.type,
        -- Prefix: role for plain text, role + kind for anything else, so
        -- a reasoning block or a tool call is never mistaken for what
        -- the model actually said.
        m.role
            || CASE
                 WHEN p.type IS NULL OR p.type = 'text' THEN ''
                 ELSE ' ' || p.type
               END
            || ': ' AS prefix,
        CASE p.type
            WHEN 'text' THEN coalesce(pt.text, '')
            WHEN 'reasoning' THEN
                CASE
                    WHEN json_extract(p.payload, '$.redacted')
                    THEN '(reasoning withheld by provider)'
                    ELSE coalesce(pt.text, '')
                END
            WHEN 'tool_call' THEN
                p.tool_name
                    || '(' || coalesce(json_extract(p.payload, '$.arguments'), '') || ')'
            WHEN 'tool_result' THEN
                p.tool_name
                    || ' -> ' || coalesce(json_extract(p.payload, '$.output'), '')
            WHEN 'attachment' THEN '(attachment)'
            ELSE coalesce(p.type, '(no content)')
        END AS body
    FROM walk w
    JOIN messages m ON m.hash = w.message_hash
    LEFT JOIN parts p ON p.message_hash = m.hash
    LEFT JOIN part_text pt ON pt.part_id = p.id
),
margined AS (
    SELECT
        r.*,
        CASE
            WHEN r.indent = 0 THEN ''
            ELSE replace(hex(zeroblob((r.indent - 1) * 8)), '00', ' ')
                 -- The branch marker occupies the last indent step, so
                 -- the head of a branch and its descendants line up.
                 || CASE
                      WHEN r.of > 1 AND coalesce(r.position, 0) = 0
                      THEN printf('%-8s', '[' || r.ord || '/' || r.of || ']')
                      ELSE '        '
                    END
        END AS margin
    FROM rendered r
)
SELECT
    -- Short, typeable handle for the whole tree. Every message reachable
    -- from one root shares it, so filtering on it gives that
    -- conversation and every branch of it.
    substr(m.root_hash, 4, 8) AS id,
    m.margin
        || m.prefix
        -- Wrapped lines sit under the prefix, so a multi-line answer
        -- stays inside its own column.
        || replace(
             m.body,
             char(10),
             char(10) || replace(
                 hex(zeroblob(length(m.margin) + length(m.prefix))), '00', ' '
             )
           ) AS entry,
    m.depth,
    m.indent,
    CASE WHEN m.of > 1 THEN m.ord ELSE NULL END AS branch,
    m.of AS branches,
    m.role,
    m.type,
    m.message_hash,
    m.root_hash,
    m.sort_key
FROM margined m
ORDER BY m.sort_key, m.position;
