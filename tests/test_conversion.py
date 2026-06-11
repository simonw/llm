"""Tests for converting legacy logged data into the node-tree schema.

The converter must be plugin-free (models from uninstalled plugins
convert fine), defensive (a malformed row never breaks the migration -
it lands in _conversion_errors), and idempotent.
"""

import json

import pytest
import sqlite_utils
from click.testing import CliRunner

from llm.cli import cli
from llm.migrations import MIGRATIONS, ensure_migrations_table, migrate


def legacy_db(tmp_path=None):
    "Build a database migrated up to (not including) the cutover."
    db = sqlite_utils.Database(memory=True)
    ensure_migrations_table(db)
    stop_at = [m.__name__ for m in MIGRATIONS].index("m024_new_responses")
    for fn in MIGRATIONS[:stop_at]:
        fn(db)
        db["_llm_migrations"].insert({"name": fn.__name__, "applied_at": "now"})
    return db


def insert_legacy_conversation(db):
    """A two-turn legacy conversation exercising fragments, attachments,
    tool definitions, tool calls/results and reasoning. The model is
    deliberately one that is not installed."""
    db["conversations"].insert(
        {"id": "conv1", "name": "test conversation", "model": "uninstalled-model"}
    )
    db["fragments"].insert(
        {
            "id": 1,
            "hash": "fragmenthash",
            "content": "fragment text",
            "datetime_utc": "2025-01-01T00:00:00",
        }
    )
    db["attachments"].insert(
        {
            "id": "att1",
            "type": "image/png",
            "path": None,
            "url": None,
            "content": b"png bytes",
        }
    )
    db["tools"].insert(
        {
            "id": 1,
            "hash": "toolhash",
            "name": "multiply",
            "description": "Multiply",
            "input_schema": "{}",
            "plugin": None,
        }
    )
    db["tool_instances"].insert(
        {"id": 1, "plugin": "SomePlugin", "name": "Some", "arguments": "{}"}
    )
    # Turn 1: system + fragment-prefixed prompt + attachment, the model
    # responds with reasoning, text and a tool call
    db["responses"].insert(
        {
            "id": "res1",
            "model": "uninstalled-model",
            "prompt": "what is in this image times 2?",
            "system": "be brief",
            "response": "I will multiply.",
            "reasoning": "thinking about it",
            "options_json": '{"temperature": 0.5}',
            "conversation_id": "conv1",
            "datetime_utc": "2025-01-01T00:00:01",
            "input_tokens": 10,
            "output_tokens": 5,
        },
        alter=True,
    )
    db["prompt_fragments"].insert({"response_id": "res1", "fragment_id": 1, "order": 0})
    db["system_fragments"].insert({"response_id": "res1", "fragment_id": 1, "order": 0})
    db["prompt_attachments"].insert(
        {"response_id": "res1", "attachment_id": "att1", "order": 0}
    )
    db["tool_responses"].insert({"tool_id": 1, "response_id": "res1"})
    db["tool_calls"].insert(
        {
            "response_id": "res1",
            "tool_id": 1,
            "name": "multiply",
            "arguments": '{"a": 2, "b": 2}',
            "tool_call_id": "call_1",
        }
    )
    # Turn 2: tool result comes back, model answers
    db["responses"].insert(
        {
            "id": "res2",
            "model": "uninstalled-model",
            "prompt": None,
            "system": None,
            "response": "The answer is 4.",
            "options_json": "{}",
            "conversation_id": "conv1",
            "datetime_utc": "2025-01-01T00:00:02",
        },
        alter=True,
    )
    tool_result_id = (
        db["tool_results"]
        .insert(
            {
                "response_id": "res2",
                "tool_id": 1,
                "name": "multiply",
                "output": "4",
                "tool_call_id": "call_1",
                "instance_id": 1,
                "exception": None,
            }
        )
        .last_pk
    )
    db["tool_results_attachments"].insert(
        {"tool_result_id": tool_result_id, "attachment_id": "att1", "order": 0}
    )
    db["tool_responses"].insert({"tool_id": 1, "response_id": "res2"})


def test_conversion_full_fidelity():
    db = legacy_db()
    insert_legacy_conversation(db)
    migrate(db)

    # The archive holds the original rows untouched
    assert db["responses_archive"].count == 2
    # Both responses converted with preserved ids
    rows = list(db["responses"].rows_where(order_by="id"))
    assert [r["id"] for r in rows] == ["res1", "res2"]
    assert rows[0]["prompt"] == "what is in this image times 2?"
    assert rows[0]["reasoning"] == "thinking about it"
    assert rows[0]["options_json"] == '{"temperature": 0.5}'
    assert rows[1]["response"] == "The answer is 4."

    # Turn 1 chain: system, user (3 messages incl. output)
    chains_1 = list(
        db.query(
            "select * from response_chains where response_id = ? order by depth",
            ["res1"],
        )
    )
    scopes_1 = [c["scope"] for c in chains_1]
    assert scopes_1 == ["input", "input", "output"]

    # Turn 2 chain extends turn 1: history (3) + tool message + output
    chains_2 = list(
        db.query(
            "select * from response_chains where response_id = ? order by depth",
            ["res2"],
        )
    )
    scopes_2 = [c["scope"] for c in chains_2]
    assert scopes_2 == ["history", "history", "history", "input", "output"]
    # Shared prefix: turn 2's history nodes are turn 1's nodes
    assert [c["node_id"] for c in chains_2[:3]] == [c["node_id"] for c in chains_1]

    # Tool call and result visible through the views
    tool_calls = list(db["response_tool_calls"].rows)
    assert len(tool_calls) == 1
    assert tool_calls[0]["response_id"] == "res1"
    assert json.loads(tool_calls[0]["arguments"]) == {"a": 2, "b": 2}
    tool_results = list(db["response_tool_results"].rows)
    assert len(tool_results) == 1
    assert tool_results[0]["response_id"] == "res2"
    assert tool_results[0]["output"] == "4"
    assert tool_results[0]["instance_id"] == 1

    # Reasoning became a structured part
    reasoning = list(db.query("""
            select parts.text from parts
            join response_chains on response_chains.message_id = parts.message_id
            where response_chains.response_id = 'res1'
              and response_chains.scope = 'output'
              and parts.type = 'reasoning'
            """))
    assert reasoning == [{"text": "thinking about it"}]

    # Fragments copied into the merged table
    frags = list(db["response_fragments"].rows)
    assert {(f["fragment_type"], f["response_id"]) for f in frags} == {
        ("prompt", "res1"),
        ("system", "res1"),
    }

    # Tool definitions linked
    assert db["response_tools"].count == 2

    # The fragment text is part of the synthesized user message, the
    # way Prompt.prompt concatenates it
    user_text = list(db.query("""
            select parts.text from parts
            join messages on messages.id = parts.message_id
            where messages.role = 'user' and parts.type = 'text'
            """))
    assert user_text == [{"text": "fragment text\nwhat is in this image times 2?"}]

    # The prompt attachment became an attachment part on the user message
    attachment_parts = list(db.query("select * from parts where type = 'attachment'"))
    assert len(attachment_parts) == 1
    assert attachment_parts[0]["attachment_id"] == "att1"

    # No conversion errors
    assert db["_conversion_errors"].count == 0


def test_conversion_is_idempotent():
    db = legacy_db()
    insert_legacy_conversation(db)
    migrate(db)
    from llm.conversion import convert_legacy_data

    counts_before = {
        name: db[name].count for name in ("responses", "messages", "nodes", "parts")
    }
    convert_legacy_data(db)
    counts_after = {
        name: db[name].count for name in ("responses", "messages", "nodes", "parts")
    }
    assert counts_before == counts_after


def test_conversion_records_errors_and_continues():
    db = legacy_db()
    insert_legacy_conversation(db)
    # A second, corrupt conversation: malformed tool call arguments
    db["conversations"].insert({"id": "conv2", "name": "bad", "model": "m"})
    db["responses"].insert(
        {
            "id": "res3",
            "model": "m",
            "prompt": "hi",
            "response": "ok",
            "options_json": "{}",
            "conversation_id": "conv2",
        },
        alter=True,
    )
    db["tool_calls"].insert(
        {
            "response_id": "res3",
            "tool_id": None,
            "name": "f",
            "arguments": "this is not json {",
            "tool_call_id": "x",
        }
    )
    migrate(db)
    # The good conversation converted, the bad one recorded
    assert {r["id"] for r in db["responses"].rows} == {"res1", "res2"}
    errors = list(db["_conversion_errors"].rows)
    assert len(errors) == 1
    assert errors[0]["conversation_id"] == "conv2"
    # The archive still has the corrupt row - nothing lost
    assert db["responses_archive"].count == 3


def test_backfill_command_retries_errors(tmp_path):
    path = str(tmp_path / "logs.db")
    db = sqlite_utils.Database(path)
    ensure_migrations_table(db)
    stop_at = [m.__name__ for m in MIGRATIONS].index("m024_new_responses")
    for fn in MIGRATIONS[:stop_at]:
        fn(db)
        db["_llm_migrations"].insert({"name": fn.__name__, "applied_at": "now"})
    db["conversations"].insert({"id": "conv2", "name": "bad", "model": "m"})
    db["responses"].insert(
        {
            "id": "res3",
            "model": "m",
            "prompt": "hi",
            "response": "ok",
            "options_json": "{}",
            "conversation_id": "conv2",
        },
        alter=True,
    )
    db["tool_calls"].insert(
        {
            "response_id": "res3",
            "tool_id": None,
            "name": "f",
            "arguments": "broken {",
            "tool_call_id": "x",
        }
    )
    migrate(db)
    assert db["_conversion_errors"].count == 1
    assert db["responses"].count == 0

    # Repair the data, then retry via the CLI
    db["tool_calls"].update(1, {"arguments": "{}"})
    runner = CliRunner()
    result = runner.invoke(cli, ["logs", "backfill", "-d", path])
    assert result.exit_code == 0, result.output
    assert db["_conversion_errors"].count == 0
    assert db["responses"].count == 1
    assert "1 response" in result.output


def test_conversion_handles_no_archive():
    # Fresh databases have no archive at all - the migration is a no-op
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    assert "responses_archive" not in db.table_names()
    assert db["responses"].count == 0


@pytest.mark.parametrize("model_installed", (False, True))
def test_converted_conversation_loads(tmp_path, mock_model, model_installed):
    # llm -c against a converted conversation works end to end when the
    # model is available
    path = str(tmp_path / "logs.db")
    db = sqlite_utils.Database(path)
    ensure_migrations_table(db)
    stop_at = [m.__name__ for m in MIGRATIONS].index("m024_new_responses")
    for fn in MIGRATIONS[:stop_at]:
        fn(db)
        db["_llm_migrations"].insert({"name": fn.__name__, "applied_at": "now"})
    model_id = "mock" if model_installed else "not-installed-model"
    db["conversations"].insert({"id": "conv1", "name": "c", "model": model_id})
    db["responses"].insert(
        {
            "id": "res1",
            "model": model_id,
            "prompt": "first question",
            "system": "be brief",
            "response": "first answer",
            "options_json": "{}",
            "conversation_id": "conv1",
        },
        alter=True,
    )
    migrate(db)
    assert db["responses"].count == 1
    if model_installed:
        from llm.cli import load_conversation

        conversation = load_conversation("conv1", database=path)
        assert len(conversation.responses) == 1
        response = conversation.responses[0]
        assert response.text() == "first answer"
        messages = response.prompt.messages
        assert [m.role for m in messages] == ["system", "user"]
        assert messages[1].parts[0].text == "first question"
