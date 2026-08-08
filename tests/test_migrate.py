import pytest
import sqlite_utils

import llm
from llm.embeddings_migrations import embeddings_migrations
from llm.migrations import migrate

EXPECTED = {
    "id": str,
    "model": str,
    "resolved_model": str,
    "prompt": str,
    "system": str,
    "prompt_json": str,
    "options_json": str,
    "response": str,
    "response_json": str,
    "conversation_id": str,
    "duration_ms": int,
    "datetime_utc": str,
    "input_tokens": int,
    "output_tokens": int,
    "token_details": str,
    "schema_id": str,
    "reasoning": str,
}


def test_migrate_blank():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert set(db.table_names()).issuperset(
        {"_llm_migrations", "conversations", "responses", "responses_fts"}
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
    ):
        assert expected_fk in foreign_keys

    # Should have FTS configured with triggers on correct tables
    assert {trigger.name for trigger in db.triggers} == {
        "responses_ai",
        "responses_ad",
        "responses_au",
        "turn_search_ai",
        "turn_search_ad",
        "turn_search_au",
    }


def test_migrate_creates_log_lookup_indexes():
    """m028: the columns `llm logs` filters and joins on are indexed,
    so listings never scan the tool, parts or responses tables."""
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    indexed = {
        (table.name, tuple(index.columns))
        for table in db.tables
        for index in table.indexes
    }
    for expected in (
        ("tool_calls", ("response_id",)),
        ("tool_results", ("response_id",)),
        ("tool_responses", ("response_id",)),
        ("responses", ("conversation_id",)),
        ("parts", ("type", "tool_name", "message_hash")),
    ):
        assert expected in indexed


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
        "turn_search_ai",
        "turn_search_ad",
        "turn_search_au",
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
