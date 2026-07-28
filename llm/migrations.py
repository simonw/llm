import datetime
from collections.abc import Callable

MIGRATIONS: list[Callable] = []
migration = MIGRATIONS.append


def migrate(db):
    ensure_migrations_table(db)
    already_applied = {r["name"] for r in db["_llm_migrations"].rows}
    for fn in MIGRATIONS:
        name = fn.__name__
        if name not in already_applied:
            fn(db)
            db["_llm_migrations"].insert(
                {
                    "name": name,
                    "applied_at": str(datetime.datetime.now(datetime.timezone.utc)),
                }
            )
            already_applied.add(name)


def ensure_migrations_table(db):
    if not db["_llm_migrations"].exists():
        db["_llm_migrations"].create(
            {
                "name": str,
                "applied_at": str,
            },
            pk="name",
        )


@migration
def m001_initial(db):
    # Ensure the original table design exists, so other migrations can run
    if db["log"].exists():
        # It needs to have the chat_id column
        if "chat_id" not in db["log"].columns_dict:
            db["log"].add_column("chat_id")
        return
    db["log"].create(
        {
            "provider": str,
            "system": str,
            "prompt": str,
            "chat_id": str,
            "response": str,
            "model": str,
            "timestamp": str,
        }
    )


@migration
def m002_id_primary_key(db):
    db["log"].transform(pk="id")


@migration
def m003_chat_id_foreign_key(db):
    db["log"].transform(types={"chat_id": int})
    db["log"].add_foreign_key("chat_id", "log", "id")


@migration
def m004_column_order(db):
    db["log"].transform(
        column_order=(
            "id",
            "model",
            "timestamp",
            "prompt",
            "system",
            "response",
            "chat_id",
        )
    )


@migration
def m004_drop_provider(db):
    db["log"].transform(drop=("provider",))


@migration
def m005_debug(db):
    db["log"].add_column("debug", str)
    db["log"].add_column("duration_ms", int)


@migration
def m006_new_logs_table(db):
    columns = db["log"].columns_dict
    for column, type in (
        ("options_json", str),
        ("prompt_json", str),
        ("response_json", str),
        ("reply_to_id", int),
    ):
        # It's possible people running development code like myself
        # might have accidentally created these columns already
        if column not in columns:
            db["log"].add_column(column, type)

    # Use .transform() to rename options and timestamp_utc, and set new order
    db["log"].transform(
        column_order=(
            "id",
            "model",
            "prompt",
            "system",
            "prompt_json",
            "options_json",
            "response",
            "response_json",
            "reply_to_id",
            "chat_id",
            "duration_ms",
            "timestamp_utc",
        ),
        rename={
            "timestamp": "timestamp_utc",
            "options": "options_json",
        },
    )


@migration
def m007_finish_logs_table(db):
    db["log"].transform(
        drop={"debug"},
        rename={"timestamp_utc": "datetime_utc"},
        drop_foreign_keys=("chat_id",),
    )
    with db.conn:
        db.execute("alter table log rename to logs")


@migration
def m008_reply_to_id_foreign_key(db):
    db["logs"].add_foreign_key("reply_to_id", "logs", "id")


@migration
def m008_fix_column_order_in_logs(db):
    # reply_to_id ended up at the end after foreign key added
    db["logs"].transform(
        column_order=(
            "id",
            "model",
            "prompt",
            "system",
            "prompt_json",
            "options_json",
            "response",
            "response_json",
            "reply_to_id",
            "chat_id",
            "duration_ms",
            "timestamp_utc",
        ),
    )


@migration
def m009_delete_logs_table_if_empty(db):
    # We moved to a new table design, but we don't delete the table
    # if someone has put data in it
    if not db["logs"].count:
        db["logs"].drop()


@migration
def m010_create_new_log_tables(db):
    db["conversations"].create(
        {
            "id": str,
            "name": str,
            "model": str,
        },
        pk="id",
    )
    db["responses"].create(
        {
            "id": str,
            "model": str,
            "prompt": str,
            "system": str,
            "prompt_json": str,
            "options_json": str,
            "response": str,
            "response_json": str,
            "conversation_id": str,
            "duration_ms": int,
            "datetime_utc": str,
        },
        pk="id",
        foreign_keys=(("conversation_id", "conversations", "id"),),
    )


@migration
def m011_fts_for_responses(db):
    db["responses"].enable_fts(["prompt", "response"], create_triggers=True)


@migration
def m012_attachments_tables(db):
    db["attachments"].create(
        {
            "id": str,
            "type": str,
            "path": str,
            "url": str,
            "content": bytes,
        },
        pk="id",
    )
    db["prompt_attachments"].create(
        {
            "response_id": str,
            "attachment_id": str,
            "order": int,
        },
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("attachment_id", "attachments", "id"),
        ),
        pk=("response_id", "attachment_id"),
    )


@migration
def m013_usage(db):
    db["responses"].add_column("input_tokens", int)
    db["responses"].add_column("output_tokens", int)
    db["responses"].add_column("token_details", str)


@migration
def m014_schemas(db):
    db["schemas"].create(
        {
            "id": str,
            "content": str,
        },
        pk="id",
    )
    db["responses"].add_column("schema_id", str, fk="schemas", fk_col="id")
    # Clean up SQL create table indentation
    db["responses"].transform()
    # These changes may have dropped the FTS configuration, fix that
    db["responses"].enable_fts(
        ["prompt", "response"], create_triggers=True, replace=True
    )


@migration
def m015_fragments_tables(db):
    db["fragments"].create(
        {
            "id": int,
            "hash": str,
            "content": str,
            "datetime_utc": str,
            "source": str,
        },
        pk="id",
    )
    db["fragments"].create_index(["hash"], unique=True)
    db["fragment_aliases"].create(
        {
            "alias": str,
            "fragment_id": int,
        },
        foreign_keys=(("fragment_id", "fragments", "id"),),
        pk="alias",
    )
    db["prompt_fragments"].create(
        {
            "response_id": str,
            "fragment_id": int,
            "order": int,
        },
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("fragment_id", "fragments", "id"),
        ),
        pk=("response_id", "fragment_id"),
    )
    db["system_fragments"].create(
        {
            "response_id": str,
            "fragment_id": int,
            "order": int,
        },
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("fragment_id", "fragments", "id"),
        ),
        pk=("response_id", "fragment_id"),
    )


@migration
def m016_fragments_table_pks(db):
    # The same fragment can be attached to a response multiple times
    # https://github.com/simonw/llm/issues/863#issuecomment-2781720064
    db["prompt_fragments"].transform(pk=("response_id", "fragment_id", "order"))
    db["system_fragments"].transform(pk=("response_id", "fragment_id", "order"))


@migration
def m017_tools_tables(db):
    db["tools"].create(
        {
            "id": int,
            "hash": str,
            "name": str,
            "description": str,
            "input_schema": str,
        },
        pk="id",
    )
    db["tools"].create_index(["hash"], unique=True)
    # Many-to-many relationship between tools and responses
    db["tool_responses"].create(
        {
            "tool_id": int,
            "response_id": str,
        },
        foreign_keys=(
            ("tool_id", "tools", "id"),
            ("response_id", "responses", "id"),
        ),
        pk=("tool_id", "response_id"),
    )
    # tool_calls and tool_results are one-to-many against responses
    db["tool_calls"].create(
        {
            "id": int,
            "response_id": str,
            "tool_id": int,
            "name": str,
            "arguments": str,
            "tool_call_id": str,
        },
        pk="id",
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("tool_id", "tools", "id"),
        ),
    )
    db["tool_results"].create(
        {
            "id": int,
            "response_id": str,
            "tool_id": int,
            "name": str,
            "output": str,
            "tool_call_id": str,
        },
        pk="id",
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("tool_id", "tools", "id"),
        ),
    )


@migration
def m017_tools_plugin(db):
    db["tools"].add_column("plugin")


@migration
def m018_tool_instances(db):
    # Used to track instances of Toolbox classes that may be
    # used multiple times by different tools
    db["tool_instances"].create(
        {
            "id": int,
            "plugin": str,
            "name": str,
            "arguments": str,
        },
        pk="id",
    )
    # We record which instance was used only on the results
    db["tool_results"].add_column("instance_id", fk="tool_instances")


@migration
def m019_resolved_model(db):
    # For models like gemini-1.5-flash-latest where we wish to record
    # the resolved model name in addition to the alias
    db["responses"].add_column("resolved_model", str)


@migration
def m020_tool_results_attachments(db):
    db["tool_results_attachments"].create(
        {
            "tool_result_id": int,
            "attachment_id": str,
            "order": int,
        },
        foreign_keys=(
            ("tool_result_id", "tool_results", "id"),
            ("attachment_id", "attachments", "id"),
        ),
        pk=("tool_result_id", "attachment_id"),
    )


@migration
def m021_tool_results_exception(db):
    db["tool_results"].add_column("exception", str)


@migration
def m022_response_reasoning(db):
    # Concatenated visible reasoning text emitted during the response.
    # NULL/empty when no reasoning was emitted or when the provider
    # only reported an opaque token count (the redacted-marker case).
    db["responses"].add_column("reasoning", str)


# Literal text of one parts row: the text column when the part's text
# is pure literal, otherwise the literal segments of a text_ref payload
# - fragment content is deliberately not searchable.
TURN_SEARCH_LITERAL = """coalesce(
  parts.text,
  (select group_concat(json_extract(je.value, '$.literal'), '')
     from json_each(parts.payload, '$.text_ref') je
    where json_extract(je.value, '$.literal') is not null)
)"""

# Derives the searchable prompt and response text for turns. Serves both
# the migration backfill (turn_filter="") and the per-turn refresh in
# LogStore.log (turn_filter="and turns.id = :turn_id" - the slot appears
# in three places so the filtered form touches only that turn's chain).
TURN_SEARCH_INSERT_SQL = """
with recursive output_messages(turn_id, hash) as (
    select turns.id, turns.tip_message_hash
      from turns
     where turns.tip_message_hash is not null
       and (turns.parent_message_hash is null
            or turns.tip_message_hash != turns.parent_message_hash)
       {turn_filter}
    union all
    select om.turn_id, messages.parent_hash
      from output_messages om
      join messages on messages.hash = om.hash
      join turns on turns.id = om.turn_id
     where messages.parent_hash is not null
       and (turns.parent_message_hash is null
            or messages.parent_hash != turns.parent_message_hash)
),
prompt_text as (
    select turns.id as turn_id,
           (select group_concat({LITERAL}, '')
              from parts
             where parts.message_hash = turns.parent_message_hash
               and parts.type = 'text'
             order by parts.position) as text
      from turns
      join messages on messages.hash = turns.parent_message_hash
     where messages.role = 'user' {turn_filter}
),
response_text as (
    select om.turn_id, group_concat(part_text.text, '') as text
      from output_messages om
      join messages on messages.hash = om.hash and messages.role = 'assistant'
      join (
          select parts.message_hash, parts.position, {LITERAL} as text
            from parts where parts.type = 'text'
      ) part_text on part_text.message_hash = om.hash
     group by om.turn_id
)
insert into turn_search (turn_id, prompt, response)
select turns.id,
       coalesce(prompt_text.text, ''),
       coalesce(response_text.text, '')
  from turns
  left join prompt_text on prompt_text.turn_id = turns.id
  left join response_text on response_text.turn_id = turns.id
 where (coalesce(prompt_text.text, '') != ''
        or coalesce(response_text.text, '') != '') {turn_filter}
""".replace("{LITERAL}", TURN_SEARCH_LITERAL)


@migration
def m023_message_store(db):
    # The content-addressed message store, created in its final form.
    # Nothing here is dropped, migrated or backfilled: these tables
    # have never existed in any released version of LLM, so a database
    # either gains them fresh or is in an unsupported development state
    # - in which case the creates below fail loudly rather than
    # touching whatever is there.
    db["messages"].create(
        {
            "hash": str,
            "parent_hash": str,
            "role": str,
            "provider_metadata": str,
        },
        pk="hash",
        foreign_keys=(("parent_hash", "messages", "hash"),),
    )
    # Needed by the recursive descent through the tree and by the
    # child count that identifies a fork.
    db["messages"].create_index(["parent_hash"])

    db["parts"].create(
        {
            "id": int,
            "message_hash": str,
            "position": int,
            # text | reasoning | tool_call | tool_result | attachment
            "type": str,
            # Tool name for tool_call and tool_result parts, else NULL.
            "tool_name": str,
            # The part's literal text, for text and reasoning parts whose
            # text borrows no fragments. Raw and unescaped - this column
            # is never parsed as anything.
            "text": str,
            # The part's remaining structure as JSON, with large content
            # replaced by references (fragment ids for text, attachment
            # ids for binary) and the type key left to the column above.
            # NULL when the text column carries everything.
            "payload": str,
        },
        pk="id",
        foreign_keys=(("message_hash", "messages", "hash"),),
    )
    # The hot read path, and it enforces one part per position.
    db["parts"].create_index(["message_hash", "position"], unique=True)

    # Attachment and fragment ids are in the payload too. These tables
    # exist so referential integrity, garbage collection reachability and
    # "everything that used X" are plain joins rather than a json_each
    # over every payload in the database.
    db["part_attachments"].create(
        {
            "part_id": int,
            "attachment_id": str,
            "order": int,
        },
        pk=("part_id", "attachment_id", "order"),
        foreign_keys=(
            ("part_id", "parts", "id"),
            ("attachment_id", "attachments", "id"),
        ),
    )

    db["part_fragments"].create(
        {
            "part_id": int,
            "fragment_id": int,
            "order": int,
        },
        pk=("part_id", "fragment_id", "order"),
        foreign_keys=(
            ("part_id", "parts", "id"),
            ("fragment_id", "fragments", "id"),
        ),
    )
    db["part_fragments"].create_index(["fragment_id"])

    # The only mutable rows in the schema. A fork is a second thread
    # pointing at a message that already exists.
    db["threads"].create(
        {
            "id": str,
            "name": str,
            "tip_message_hash": str,
            "forked_from": str,
            "datetime_utc": str,
        },
        pk="id",
        foreign_keys=(
            ("tip_message_hash", "messages", "hash"),
            ("forked_from", "threads", "id"),
        ),
    )

    # One model call. Self-contained - it does not read anything from the
    # older responses table. parent_ and tip_message_hash together
    # delimit what this turn contributed, which nothing else records,
    # because message rows are shared and cannot carry provenance.
    db["turns"].create(
        {
            "id": str,
            "thread_id": str,
            "parent_message_hash": str,
            "tip_message_hash": str,
            "model": str,
            "resolved_model": str,
            "options_json": str,
            "schema_id": str,
            "input_tokens": int,
            "output_tokens": int,
            "token_details": str,
            "duration_ms": int,
            "datetime_utc": str,
        },
        pk="id",
        foreign_keys=(
            ("thread_id", "threads", "id"),
            ("parent_message_hash", "messages", "hash"),
            ("tip_message_hash", "messages", "hash"),
            ("schema_id", "schemas", "id"),
        ),
    )
    db["turns"].create_index(["thread_id"])

    db["turn_tools"].create(
        {"turn_id": str, "tool_id": int},
        pk=("turn_id", "tool_id"),
        foreign_keys=(("turn_id", "turns", "id"), ("tool_id", "tools", "id")),
    )

    # Provenance: which fragments this call was given. Distinct from
    # part_fragments, which says what a message's text is built from.
    db["turn_fragments"].create(
        {
            "turn_id": str,
            "fragment_id": int,
            "order": int,
            "kind": str,  # 'prompt' | 'system'
        },
        pk=("turn_id", "fragment_id", "kind", "order"),
        foreign_keys=(
            ("turn_id", "turns", "id"),
            ("fragment_id", "fragments", "id"),
        ),
    )
    db["turn_fragments"].create_index(["fragment_id"])

    # Searchable text per turn: the user's typed prompt (fragment
    # content excluded) and the assistant's text output, kept fresh by
    # LogStore.log. An explicit id primary key because external-content
    # FTS is keyed by rowid, and implicit rowids are not stable across
    # VACUUM.
    db["turn_search"].create(
        {
            "id": int,
            "turn_id": str,
            "prompt": str,
            "response": str,
        },
        pk="id",
        foreign_keys=(("turn_id", "turns", "id"),),
    )
    db["turn_search"].create_index(["turn_id"], unique=True)
    db["turn_search"].enable_fts(["prompt", "response"], create_triggers=True)

    # Which configured toolbox instance served a tool call: the toolbox
    # name, its plugin and its constructor arguments. Local execution
    # provenance, so it lives outside the hashed message tree, joined
    # to the chain by tool_call_id - and keyed by (turn_id,
    # tool_call_id), because provider-supplied call ids are not
    # guaranteed unique across turns. Deliberately the seed of a fuller
    # execution-events table: duration or exception details would be
    # additive columns here.
    db["tool_instantiations"].create(
        {
            "turn_id": str,
            "tool_call_id": str,
            "name": str,
            "plugin": str,
            "arguments": str,
        },
        pk=("turn_id", "tool_call_id"),
        foreign_keys=(("turn_id", "turns", "id"),),
    )
