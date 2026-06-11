import datetime
from typing import Callable, List

MIGRATIONS: List[Callable] = []
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


@migration
def m023_parts_tables(db):
    # Content-addressed Message/Part value storage plus the node tree
    # identity layer. Messages are pure values: the id is a hash of the
    # canonical JSON form, so identical content is stored once. Nodes
    # give content a position - a conversation chain is the path from a
    # root node (parent NULL) to a leaf.
    db["messages"].create(
        {
            "id": str,
            "role": str,
            "provider_metadata": str,
        },
        pk="id",
    )
    db["parts"].create(
        {
            "id": int,
            "message_id": str,
            "order": int,
            "type": str,
            "text": str,
            "redacted": int,
            "name": str,
            "arguments": str,
            "output": str,
            "tool_call_id": str,
            "server_executed": int,
            "exception": str,
            "instance_id": int,
            "attachment_id": str,
            "provider_metadata": str,
        },
        pk="id",
        foreign_keys=(
            ("message_id", "messages", "id"),
            ("instance_id", "tool_instances", "id"),
            ("attachment_id", "attachments", "id"),
        ),
    )
    db["parts"].create_index(["message_id", "order"], unique=True)
    db["parts"].create_index(["tool_call_id"])
    # Ordered attachment lists for tool_result parts; attachment parts
    # use the 1:1 parts.attachment_id column instead
    db["part_attachments"].create(
        {
            "part_id": int,
            "attachment_id": str,
            "order": int,
        },
        pk=("part_id", "order"),
        foreign_keys=(
            ("part_id", "parts", "id"),
            ("attachment_id", "attachments", "id"),
        ),
    )
    db["nodes"].create(
        {
            "id": str,
            "parent_id": str,
            "message_id": str,
            "depth": int,
        },
        pk="id",
        foreign_keys=(
            ("parent_id", "nodes", "id"),
            ("message_id", "messages", "id"),
        ),
    )
    # The lookup that makes prefix walking cheap: nodes are deduplicated
    # on (parent_id, message_id) by storage.ensure_node()
    db["nodes"].create_index(["parent_id", "message_id"])


RESPONSE_CHAINS_VIEW = """
create view response_chains as
with recursive chain (
    response_id, node_id, parent_id, message_id, depth,
    first_input_depth, input_depth
) as (
    select
        responses.id, nodes.id, nodes.parent_id, nodes.message_id, nodes.depth,
        coalesce(
            (select depth from nodes n2 where n2.id = responses.first_input_node_id),
            1000000000
        ),
        coalesce(
            (select depth from nodes n3 where n3.id = responses.input_node_id),
            -1
        )
    from responses
    join nodes on nodes.id = coalesce(
        responses.output_node_id, responses.input_node_id
    )
    union all
    select
        chain.response_id, nodes.id, nodes.parent_id, nodes.message_id,
        nodes.depth, chain.first_input_depth, chain.input_depth
    from chain
    join nodes on nodes.id = chain.parent_id
)
select
    response_id,
    node_id,
    message_id,
    depth,
    case
        when depth > input_depth then 'output'
        when depth >= first_input_depth then 'input'
        else 'history'
    end as scope
from chain
"""

RESPONSE_TOOL_CALLS_VIEW = """
create view response_tool_calls as
select
    chains.response_id,
    parts.id as part_id,
    parts.name,
    parts.arguments,
    parts.tool_call_id,
    parts.server_executed,
    parts.provider_metadata,
    chains.depth,
    parts."order"
from response_chains chains
join parts on parts.message_id = chains.message_id
where chains.scope = 'output' and parts.type = 'tool_call'
"""

RESPONSE_TOOL_RESULTS_VIEW = """
create view response_tool_results as
select
    chains.response_id,
    parts.id as part_id,
    parts.name,
    parts.output,
    parts.tool_call_id,
    parts.server_executed,
    parts.exception,
    parts.instance_id,
    chains.depth,
    parts."order"
from response_chains chains
join parts on parts.message_id = chains.message_id
where chains.scope = 'input' and parts.type = 'tool_result'
"""

RESPONSE_ATTACHMENTS_VIEW = """
create view response_attachments as
select
    chains.response_id,
    parts.attachment_id,
    chains.depth,
    parts."order"
from response_chains chains
join parts on parts.message_id = chains.message_id
where chains.scope = 'input'
    and parts.type = 'attachment'
    and parts.attachment_id is not null
"""


@migration
def m024_new_responses(db):
    # Retire the legacy responses table in favour of one backed by the
    # node tree. Logged data is never deleted or modified: the legacy
    # table is renamed to responses_archive when it holds data (a
    # metadata-only operation) and its satellite tables keep their rows
    # under their existing names. Only two kinds of drop happen here:
    # the legacy FTS index (derived data, replaced by the new table's
    # FTS over the converted rows) and legacy tables that are entirely
    # empty (the m009 precedent).
    legacy_satellites = (
        "tool_calls",
        "tool_results",
        "tool_results_attachments",
        "prompt_attachments",
        "prompt_fragments",
        "system_fragments",
        "tool_responses",
    )
    if db["responses"].exists():
        db["responses"].disable_fts()
        if not db["responses"].count:
            for name in legacy_satellites:
                if db[name].exists() and not db[name].count:
                    db[name].drop()
            db["responses"].drop()
        else:
            with db.conn:
                db.execute("alter table responses rename to responses_archive")
    db["responses"].create(
        {
            "id": str,
            "model": str,
            "resolved_model": str,
            "conversation_id": str,
            "input_node_id": str,
            "first_input_node_id": str,
            "output_node_id": str,
            "prompt": str,
            "system": str,
            "response": str,
            "reasoning": str,
            "options_json": str,
            "schema_id": str,
            "prompt_json": str,
            "response_json": str,
            "duration_ms": int,
            "datetime_utc": str,
            "input_tokens": int,
            "output_tokens": int,
            "token_details": str,
        },
        pk="id",
        foreign_keys=(
            ("conversation_id", "conversations", "id"),
            ("input_node_id", "nodes", "id"),
            ("first_input_node_id", "nodes", "id"),
            ("output_node_id", "nodes", "id"),
            ("schema_id", "schemas", "id"),
        ),
    )
    db["responses"].create_index(["conversation_id"])
    db["responses"].enable_fts(["prompt", "response"], create_triggers=True)
    # prompt_fragments + system_fragments were always one relation with
    # a type flag - store them that way now
    db["response_fragments"].create(
        {
            "response_id": str,
            "fragment_id": int,
            "fragment_type": str,
            "order": int,
        },
        pk=("response_id", "fragment_type", "order"),
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("fragment_id", "fragments", "id"),
        ),
    )
    # Which tool definitions were offered to the prompt
    db["response_tools"].create(
        {
            "response_id": str,
            "tool_id": int,
        },
        pk=("response_id", "tool_id"),
        foreign_keys=(
            ("response_id", "responses", "id"),
            ("tool_id", "tools", "id"),
        ),
    )
    # Legacy rows the converter could not handle, for llm logs backfill
    db["_conversion_errors"].create(
        {
            "id": int,
            "conversation_id": str,
            "response_id": str,
            "error": str,
            "datetime_utc": str,
        },
        pk="id",
    )
    with db.conn:
        db.execute(RESPONSE_CHAINS_VIEW)
        db.execute(RESPONSE_TOOL_CALLS_VIEW)
        db.execute(RESPONSE_TOOL_RESULTS_VIEW)
        db.execute(RESPONSE_ATTACHMENTS_VIEW)
