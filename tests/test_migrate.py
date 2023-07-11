from llm.migrations import migrate
import pytest
import sqlite_utils


EXPECTED = {
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
}


def test_migrate_blank():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert set(db.table_names()) == {"_llm_migrations", "conversations", "responses"}
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
    expected_tables = {"_llm_migrations", "conversations", "responses"}
    if has_record:
        expected_tables.add("logs")
    assert set(db.table_names()) == expected_tables
