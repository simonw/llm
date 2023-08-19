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
                {"name": name, "applied_at": str(datetime.datetime.utcnow())}
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
