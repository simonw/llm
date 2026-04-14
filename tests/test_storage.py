"""Tests for MessageStore — DAG-shaped message persistence."""

import pytest
import sqlite_utils

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
