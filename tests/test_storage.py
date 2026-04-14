"""Tests for MessageStore — DAG-shaped message persistence."""

import pytest
import sqlite_utils

import llm
from llm._canonical import message_content_hash
from llm.migrations import migrate
from llm.parts import Message, TextPart, ToolCallPart
from llm.storage import ROOT_ID, MessageStore


@pytest.fixture
def db(tmp_path):
    db = sqlite_utils.Database(str(tmp_path / "t.db"))
    migrate(db)
    return db


class TestSchema:
    def test_sentinel_root_row_exists(self, db):
        row = db.execute(
            "SELECT id, parent_id FROM messages WHERE id = ?", [ROOT_ID]
        ).fetchone()
        assert row is not None
        # Self-referencing sentinel so parent_id is NOT NULL for every row.
        assert row[0] == ROOT_ID
        assert row[1] == ROOT_ID

    def test_messages_columns(self, db):
        cols = db["messages"].columns_dict
        assert "parent_id" in cols
        assert "content_hash" in cols
        assert "role" in cols
        assert "provider_metadata_json" in cols
        assert "created_at" in cols
        # Old shape gone.
        assert "direction" not in cols
        assert "response_id" not in cols
        assert "order" not in cols

    def test_calls_table_exists(self, db):
        assert "calls" in db.table_names()
        cols = db["calls"].columns_dict
        for name in [
            "id",
            "conversation_id",
            "head_input_message_id",
            "head_output_message_id",
            "model",
            "resolved_model",
            "started_at",
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "token_details_json",
            "prompt_json",
            "response_json",
            "error",
        ]:
            assert name in cols, f"calls missing {name}"

    def test_conversations_has_head_message_id(self, db):
        assert "head_message_id" in db["conversations"].columns_dict

    def test_parent_hash_unique_index(self, db):
        indexes = {ix.name for ix in db["messages"].indexes}
        assert "idx_messages_parent_hash_unique" in indexes


class TestSaveChain:
    def test_save_single_message_creates_root_child(self, db):
        store = MessageStore(db)
        head = store.save_chain([Message(role="user", parts=[TextPart(text="hi")])])
        row = db.execute(
            "SELECT parent_id, role, content_hash FROM messages WHERE id = ?",
            [head],
        ).fetchone()
        assert row[0] == ROOT_ID  # Chain root's parent is the sentinel.
        assert row[1] == "user"
        assert row[2] == message_content_hash(
            Message(role="user", parts=[TextPart(text="hi")])
        )

    def test_save_chain_links_parent_ids(self, db):
        store = MessageStore(db)
        msgs = [
            Message(role="system", parts=[TextPart(text="sys")]),
            Message(role="user", parts=[TextPart(text="q")]),
            Message(role="assistant", parts=[TextPart(text="a")]),
        ]
        head = store.save_chain(msgs)
        # Walk back.
        chain = []
        cur = head
        while cur != ROOT_ID:
            row = db.execute(
                "SELECT id, parent_id, role FROM messages WHERE id = ?", [cur]
            ).fetchone()
            chain.append(row)
            cur = row[1]
        chain.reverse()
        assert [r[2] for r in chain] == ["system", "user", "assistant"]

    def test_save_chain_dedups_identical_prefix(self, db):
        store = MessageStore(db)
        msgs = [
            Message(role="user", parts=[TextPart(text="q1")]),
            Message(role="assistant", parts=[TextPart(text="a1")]),
        ]
        head1 = store.save_chain(msgs)
        count1 = db["messages"].count
        head2 = store.save_chain(msgs)
        count2 = db["messages"].count
        assert head1 == head2
        assert count1 == count2

    def test_save_chain_writes_only_new_tail(self, db):
        store = MessageStore(db)
        base = [
            Message(role="user", parts=[TextPart(text="q1")]),
            Message(role="assistant", parts=[TextPart(text="a1")]),
        ]
        store.save_chain(base)
        count_after_first = db["messages"].count
        extended = base + [
            Message(role="user", parts=[TextPart(text="q2")]),
        ]
        store.save_chain(extended)
        # Only one new message inserted.
        assert db["messages"].count == count_after_first + 1

    def test_parent_hash_unique_index_prevents_duplicates(self, db):
        """Even with starting_parent_id, the same (parent, content) is one row."""
        store = MessageStore(db)
        head1 = store.save_chain([Message(role="user", parts=[TextPart(text="x")])])
        # Same message again — should find-and-return, not insert.
        head2 = store.save_chain([Message(role="user", parts=[TextPart(text="x")])])
        assert head1 == head2
        # Only one non-sentinel row.
        assert db["messages"].count == 2  # sentinel + one real

    def test_different_parents_produce_different_rows(self, db):
        """Same content under different parents is a different message."""
        store = MessageStore(db)
        a = store.save_chain([Message(role="user", parts=[TextPart(text="same")])])
        b = store.save_chain(
            [
                Message(role="user", parts=[TextPart(text="different")]),
                Message(role="user", parts=[TextPart(text="same")]),
            ]
        )
        assert a != b

    def test_save_chain_writes_parts(self, db):
        store = MessageStore(db)
        head = store.save_chain(
            [
                Message(
                    role="assistant",
                    parts=[
                        TextPart(text="answer"),
                        ToolCallPart(
                            name="search",
                            arguments={"q": "x"},
                            tool_call_id="c1",
                        ),
                    ],
                )
            ]
        )
        part_rows = list(
            db.execute(
                'SELECT part_type, content, tool_call_id FROM message_parts '
                'WHERE message_id = ? ORDER BY "order"',
                [head],
            ).fetchall()
        )
        assert [p[0] for p in part_rows] == ["text", "tool_call"]
        assert part_rows[0][1] == "answer"
        assert part_rows[1][2] == "c1"

    def test_save_chain_with_starting_parent(self, db):
        store = MessageStore(db)
        h1 = store.save_chain([Message(role="user", parts=[TextPart(text="a")])])
        h2 = store.save_chain(
            [Message(role="assistant", parts=[TextPart(text="b")])],
            starting_parent_id=h1,
        )
        parent = db.execute(
            "SELECT parent_id FROM messages WHERE id = ?", [h2]
        ).fetchone()[0]
        assert parent == h1


class TestLoadChain:
    def test_load_round_trips(self, db):
        store = MessageStore(db)
        original = [
            Message(role="system", parts=[TextPart(text="sys")]),
            Message(role="user", parts=[TextPart(text="q")]),
            Message(
                role="assistant",
                parts=[
                    TextPart(text="a"),
                    ToolCallPart(
                        name="f", arguments={"n": 1}, tool_call_id="c1"
                    ),
                ],
            ),
        ]
        head = store.save_chain(original)
        loaded = store.load_chain(head)
        assert len(loaded) == 3
        assert loaded[0].role == "system"
        assert loaded[2].parts[0].text == "a"
        assert loaded[2].parts[1].tool_call_id == "c1"
        # Hashes match — canonical round-trip.
        for orig, got in zip(original, loaded):
            assert message_content_hash(orig) == message_content_hash(got)

    def test_load_stops_at_sentinel(self, db):
        store = MessageStore(db)
        head = store.save_chain([Message(role="user", parts=[TextPart(text="one")])])
        loaded = store.load_chain(head)
        assert len(loaded) == 1
        assert ROOT_ID not in [m.role for m in loaded]

    def test_find_longest_prefix_empty_db(self, db):
        store = MessageStore(db)
        last, matched = store.find_longest_existing_prefix(
            [Message(role="user", parts=[TextPart(text="hi")])]
        )
        assert last is None
        assert matched == 0

    def test_find_longest_prefix_full_match(self, db):
        store = MessageStore(db)
        msgs = [
            Message(role="user", parts=[TextPart(text="q")]),
            Message(role="assistant", parts=[TextPart(text="a")]),
        ]
        head = store.save_chain(msgs)
        last, matched = store.find_longest_existing_prefix(msgs)
        assert last == head
        assert matched == 2

    def test_find_longest_prefix_partial_match(self, db):
        store = MessageStore(db)
        base = [
            Message(role="user", parts=[TextPart(text="q1")]),
            Message(role="assistant", parts=[TextPart(text="a1")]),
        ]
        store.save_chain(base)
        extended = base + [
            Message(role="user", parts=[TextPart(text="q2")]),
            Message(role="assistant", parts=[TextPart(text="a2")]),
        ]
        last, matched = store.find_longest_existing_prefix(extended)
        assert matched == 2
        assert last is not None

    def test_save_with_dedup_writes_zero_rows_when_full_match(self, db):
        store = MessageStore(db)
        msgs = [
            Message(role="user", parts=[TextPart(text="q")]),
            Message(role="assistant", parts=[TextPart(text="a")]),
        ]
        store.save_with_dedup(msgs)
        before = db["messages"].count
        head = store.save_with_dedup(msgs)
        after = db["messages"].count
        assert after == before
        # Returned head is the existing tail.
        assert db.execute(
            "SELECT role FROM messages WHERE id = ?", [head]
        ).fetchone()[0] == "assistant"

    def test_save_with_dedup_appends_only_new_tail(self, db):
        store = MessageStore(db)
        base = [
            Message(role="user", parts=[TextPart(text="q1")]),
            Message(role="assistant", parts=[TextPart(text="a1")]),
        ]
        store.save_with_dedup(base)
        before = db["messages"].count
        extended = base + [Message(role="user", parts=[TextPart(text="q2")])]
        store.save_with_dedup(extended)
        assert db["messages"].count == before + 1  # only q2 added

    def test_load_preserves_provider_metadata(self, db):
        store = MessageStore(db)
        msg = Message(
            role="assistant",
            parts=[TextPart(text="x", provider_metadata={"anthropic": {"sig": "s"}})],
            provider_metadata={"msg_id": "m1"},
        )
        head = store.save_chain([msg])
        loaded = store.load_chain(head)
        assert loaded[0].provider_metadata == {"msg_id": "m1"}
        assert loaded[0].parts[0].provider_metadata == {
            "anthropic": {"sig": "s"}
        }


class TestConversationContinuation:
    """head_message_id advances on each log_to_db; a second turn extends
    the existing chain rather than branching a parallel one."""

    def test_head_message_id_round_trips(self, db, mock_model):
        mock_model.enqueue(["hi back"])
        conv = mock_model.conversation()
        r = conv.prompt("hi")
        r.text()
        r.log_to_db(db)
        # DB row reflects the new head.
        row = db["conversations"].get(conv.id)
        assert row["head_message_id"] == conv.head_message_id
        # Reload the conversation and check head survives.
        reloaded = llm.Conversation.from_row(row)
        assert reloaded.head_message_id == conv.head_message_id

    def test_second_turn_extends_chain(self, db, mock_model):
        mock_model.enqueue(["a1"])
        conv = mock_model.conversation()
        r1 = conv.prompt("q1")
        r1.text()
        r1.log_to_db(db)
        count_after_first = db["messages"].count
        head_after_first = conv.head_message_id

        mock_model.enqueue(["a2"])
        r2 = conv.prompt("q2")
        r2.text()
        r2.log_to_db(db)
        # Two new messages: q2 (user) + a2 (assistant); head advances.
        assert db["messages"].count == count_after_first + 2
        assert conv.head_message_id != head_after_first
        # Walking back from the new head eventually hits the previous head.
        cur = conv.head_message_id
        seen = []
        while cur != ROOT_ID:
            seen.append(cur)
            cur = db.execute(
                "SELECT parent_id FROM messages WHERE id = ?", [cur]
            ).fetchone()[0]
        assert head_after_first in seen


class TestFork:
    def test_fork_creates_new_conversation_pointing_at_source(
        self, db, mock_model
    ):
        mock_model.enqueue(["a1"])
        conv = mock_model.conversation()
        r = conv.prompt("q1")
        r.text()
        r.log_to_db(db)
        source = conv.head_message_id
        new_id = MessageStore(db).fork(source, name="branch-a")
        row = db["conversations"].get(new_id)
        assert row["head_message_id"] == source
        assert row["name"] == "branch-a"
        assert row["model"] == "mock"
        # Original conversation untouched.
        assert db["conversations"].get(conv.id)["head_message_id"] == source

    def test_fork_unknown_message_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            MessageStore(db).fork("no-such-id")

    def test_fork_without_calls_and_without_model_raises(self, db):
        """A message inserted without any calls row needs an explicit model."""
        store = MessageStore(db)
        head = store.save_chain([Message(role="user", parts=[TextPart(text="hi")])])
        with pytest.raises(ValueError, match="cannot infer model"):
            store.fork(head)

    def test_fork_with_explicit_model(self, db):
        store = MessageStore(db)
        head = store.save_chain([Message(role="user", parts=[TextPart(text="hi")])])
        new_id = store.fork(head, model="mock")
        assert db["conversations"].get(new_id)["model"] == "mock"


class TestForkCLI:
    def test_fork_cli_prints_new_conversation_id(
        self, db, mock_model, user_path
    ):
        import pathlib

        from click.testing import CliRunner

        from llm.cli import cli

        mock_model.enqueue(["a1"])
        conv = mock_model.conversation()
        r = conv.prompt("q1")
        r.text()
        # Write to the standard logs path used by the CLI.
        logs_path = pathlib.Path(user_path) / "logs.db"
        real_db = sqlite_utils.Database(str(logs_path))
        migrate(real_db)
        r.log_to_db(real_db)
        source = conv.head_message_id

        runner = CliRunner()
        result = runner.invoke(cli, ["fork", source], catch_exceptions=False)
        assert result.exit_code == 0
        new_id = result.output.strip()
        row = real_db["conversations"].get(new_id)
        assert row["head_message_id"] == source
