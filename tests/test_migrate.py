from llm.migrations import migrate
import sqlite_utils


EXPECTED = {
    "id": int,
    "model": str,
    "prompt": str,
    "system": str,
    "prompt_json": str,
    "options_json": str,
    "response": str,
    "response_json": str,
    "reply_to_id": int,
    "chat_id": int,
    "duration_ms": int,
    "datetime_utc": str,
}


def test_migrate_blank():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert set(db.table_names()) == {"_llm_migrations", "logs"}
    assert db["logs"].columns_dict == EXPECTED

    foreign_keys = db["logs"].foreign_keys
    for expected_fk in (
        sqlite_utils.db.ForeignKey(
            table="logs", column="reply_to_id", other_table="logs", other_column="id"
        ),
        sqlite_utils.db.ForeignKey(
            table="logs", column="chat_id", other_table="logs", other_column="id"
        ),
    ):
        assert expected_fk in foreign_keys


def test_migrate_from_original_schema():
    db = sqlite_utils.Database(memory=True)
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
    migrate(db)
    assert set(db.table_names()) == {"_llm_migrations", "logs"}
    assert db["logs"].columns_dict == EXPECTED
