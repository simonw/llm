from llm.migrations import migrate
import sqlite_utils


def test_migrate_blank():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert set(db.table_names()) == {"_llm_migrations", "log"}
    assert db["log"].columns_dict == {
        "id": int,
        "model": str,
        "timestamp": str,
        "prompt": str,
        "system": str,
        "response": str,
        "chat_id": int,
        "debug": str,
        "duration_ms": int,
    }


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
    assert set(db.table_names()) == {"_llm_migrations", "log"}
    schema = db["log"].schema
    assert db["log"].columns_dict == {
        "id": int,
        "model": str,
        "timestamp": str,
        "prompt": str,
        "system": str,
        "response": str,
        "chat_id": int,
        "debug": str,
        "duration_ms": int,
    }
