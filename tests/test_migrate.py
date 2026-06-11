import llm
from llm.migrations import migrate
from llm.embeddings_migrations import embeddings_migrations
import pytest
import sqlite_utils

EXPECTED = {
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
}


def test_migrate_blank():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert set(db.table_names()).issuperset(
        {
            "_llm_migrations",
            "conversations",
            "responses",
            "responses_fts",
            "messages",
            "parts",
            "part_attachments",
            "nodes",
            "response_fragments",
            "response_tools",
        }
    )
    assert db["responses"].columns_dict == EXPECTED

    foreign_keys = db["responses"].foreign_keys
    for expected_fk in (
        sqlite_utils.db.ForeignKey(
            table="responses",
            column="conversation_id",
            other_table="conversations",
            other_column="id",
        ),
        sqlite_utils.db.ForeignKey(
            table="responses",
            column="input_node_id",
            other_table="nodes",
            other_column="id",
        ),
        sqlite_utils.db.ForeignKey(
            table="responses",
            column="output_node_id",
            other_table="nodes",
            other_column="id",
        ),
    ):
        assert expected_fk in foreign_keys

    # Should have FTS configured with triggers on correct tables
    assert {trigger.name for trigger in db.triggers} == {
        "responses_ai",
        "responses_ad",
        "responses_au",
    }

    # The chain views should exist
    assert set(db.view_names()).issuperset(
        {
            "response_chains",
            "response_tool_calls",
            "response_tool_results",
            "response_attachments",
        }
    )

    # Empty legacy tables are dropped on a fresh database
    for legacy in (
        "tool_calls",
        "tool_results",
        "prompt_attachments",
        "prompt_fragments",
        "system_fragments",
        "tool_responses",
        "responses_archive",
    ):
        assert legacy not in db.table_names()


def test_migrate_legacy_data_archived():
    # A database with existing logged data: the legacy responses table
    # is renamed to responses_archive with every row preserved, and the
    # populated satellite tables keep their names and rows.
    db = sqlite_utils.Database(memory=True)
    from llm.migrations import MIGRATIONS, ensure_migrations_table

    ensure_migrations_table(db)
    stop_at = [m.__name__ for m in MIGRATIONS].index("m024_new_responses")
    for fn in MIGRATIONS[:stop_at]:
        fn(db)
        db["_llm_migrations"].insert(
            {"name": fn.__name__, "applied_at": "now"}, replace=True
        )
    db["conversations"].insert({"id": "c1", "name": "test", "model": "m"})
    db["responses"].insert(
        {
            "id": "r1",
            "model": "m",
            "prompt": "hello",
            "response": "world",
            "conversation_id": "c1",
        },
        alter=True,
    )
    db["tool_calls"].insert(
        {"response_id": "r1", "name": "f", "arguments": "{}", "tool_call_id": "t1"}
    )
    migrate(db)
    assert "responses_archive" in db.table_names()
    archived = list(db["responses_archive"].rows)
    assert len(archived) == 1
    assert archived[0]["prompt"] == "hello"
    # Populated satellite tables survive untouched
    assert db["tool_calls"].count == 1
    # The new responses table is in place with the new schema
    assert db["responses"].columns_dict == EXPECTED


@pytest.mark.parametrize("has_record", [True, False])
def test_migrate_from_original_schema(has_record):
    db = sqlite_utils.Database(memory=True)
    if has_record:
        db["log"].insert(
            {
                "provider": "provider",
                "system": "system",
                "prompt": "prompt",
                "chat_id": None,
                "response": "response",
                "model": "model",
                "timestamp": "timestamp",
            },
        )
    else:
        # Create empty logs table
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
    migrate(db)
    expected_tables = {"_llm_migrations", "conversations", "responses", "responses_fts"}
    if has_record:
        expected_tables.add("logs")
    assert set(db.table_names()).issuperset(expected_tables)
    assert {trigger.name for trigger in db.triggers} == {
        "responses_ai",
        "responses_ad",
        "responses_au",
    }


def test_migrations_with_legacy_alter_table():
    # https://github.com/simonw/llm/issues/162
    db = sqlite_utils.Database(memory=True)
    db.execute("pragma legacy_alter_table=on")
    migrate(db)


def test_migrations_for_embeddings():
    db = sqlite_utils.Database(memory=True)
    embeddings_migrations.apply(db)
    assert db["collections"].columns_dict == {"id": int, "name": str, "model": str}
    assert db["embeddings"].columns_dict == {
        "collection_id": int,
        "id": str,
        "embedding": bytes,
        "content": str,
        "content_blob": bytes,
        "content_hash": bytes,
        "metadata": str,
        "updated": int,
    }
    assert db["embeddings"].foreign_keys[0].column == "collection_id"
    assert db["embeddings"].foreign_keys[0].other_table == "collections"


def test_backfill_content_hash():
    db = sqlite_utils.Database(memory=True)
    # Run migrations up to but not including m004_store_content_hash
    embeddings_migrations.apply(db, stop_before="m004_store_content_hash")
    assert "content_hash" not in db["embeddings"].columns_dict
    # Add some some directly directly because llm.Collection would run migrations
    db["embeddings"].insert_all(
        [
            {
                "collection_id": 1,
                "id": "1",
                "embedding": (
                    b"\x00\x00\xa0@\x00\x00\xa0@\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                ),
                "content": None,
                "metadata": None,
                "updated": 1693763088,
            },
            {
                "collection_id": 1,
                "id": "2",
                "embedding": (
                    b"\x00\x00\xe0@\x00\x00\xa0@\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                ),
                "content": "goodbye world",
                "metadata": None,
                "updated": 1693763088,
            },
        ]
    )
    # Now finish the migrations
    embeddings_migrations.apply(db)
    row1, row2 = db["embeddings"].rows
    # This one should be random:
    assert row1["content_hash"] is not None
    # This should be a hash of 'goodbye world'
    assert row2["content_hash"] == llm.Collection.content_hash("goodbye world")
