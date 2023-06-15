from llm.migrations import migrate
import sqlite_utils


def test_migrate_blank():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert set(db.table_names()) == {"_llm_migrations", "log"}
    assert db["log"].schema == (
        'CREATE TABLE "log" (\n'
        "   [id] INTEGER PRIMARY KEY,\n"
        "   [model] TEXT,\n"
        "   [timestamp] TEXT,\n"
        "   [prompt] TEXT,\n"
        "   [system] TEXT,\n"
        "   [response] TEXT,\n"
        "   [chat_id] INTEGER REFERENCES [log]([id])\n"
        ")"
    )


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
    assert schema == (
        'CREATE TABLE "log" (\n'
        "   [id] INTEGER PRIMARY KEY,\n"
        "   [model] TEXT,\n"
        "   [timestamp] TEXT,\n"
        "   [prompt] TEXT,\n"
        "   [system] TEXT,\n"
        "   [response] TEXT,\n"
        "   [chat_id] INTEGER REFERENCES [log]([id])\n"
        ")"
    )
