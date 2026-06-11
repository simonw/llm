"""Tests for llm.storage — persistence of Message/Part values and nodes.

The round-trip contract: rows_to_message(message_to_rows(m)).to_dict()
must equal m.to_dict() for every Part type with every optional field
present and absent.
"""

import pytest
import sqlite_utils

from llm import Attachment
from llm import storage
from llm.migrations import migrate
from llm.parts import (
    AttachmentPart,
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)


@pytest.fixture
def db():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    return db


ROUND_TRIP_MESSAGES = [
    pytest.param(Message(role="user", parts=[TextPart(text="hello")]), id="text"),
    pytest.param(
        Message(
            role="assistant",
            parts=[TextPart(text="hi", provider_metadata={"signature": "abc"})],
            provider_metadata={"anthropic": {"id": "msg_1"}},
        ),
        id="text-metadata",
    ),
    pytest.param(
        Message(
            role="assistant",
            parts=[ReasoningPart(text="thinking..."), TextPart(text="answer")],
        ),
        id="reasoning-then-text",
    ),
    pytest.param(
        Message(role="assistant", parts=[ReasoningPart(text="", redacted=True)]),
        id="redacted-reasoning",
    ),
    pytest.param(
        Message(
            role="assistant",
            parts=[
                ToolCallPart(
                    name="search",
                    arguments={"q": "pelicans", "n": 3},
                    tool_call_id="call_1",
                    server_executed=True,
                    provider_metadata={"gemini": {"thoughtSignature": "xyz"}},
                )
            ],
        ),
        id="tool-call",
    ),
    pytest.param(
        Message(
            role="assistant",
            parts=[ToolCallPart(name="noargs", arguments={})],
        ),
        id="tool-call-minimal",
    ),
    pytest.param(
        Message(
            role="tool",
            parts=[
                ToolResultPart(
                    name="search",
                    output="42 results",
                    tool_call_id="call_1",
                    exception="ValueError: bad input",
                )
            ],
        ),
        id="tool-result",
    ),
    pytest.param(
        Message(
            role="tool",
            parts=[
                ToolResultPart(
                    name="render",
                    output="image attached",
                    tool_call_id="call_2",
                    attachments=[
                        Attachment(type="image/png", content=b"fake png bytes"),
                        Attachment(type="text/plain", url="https://example.com/x.txt"),
                    ],
                )
            ],
        ),
        id="tool-result-attachments",
    ),
    pytest.param(
        Message(
            role="user",
            parts=[
                TextPart(text="describe this"),
                AttachmentPart(
                    attachment=Attachment(type="image/jpeg", content=b"jpeg bytes")
                ),
            ],
        ),
        id="user-attachment",
    ),
    pytest.param(
        Message(role="user", parts=[AttachmentPart(attachment=None)]),
        id="empty-attachment-part",
    ),
    pytest.param(
        Message(
            role="user",
            parts=[
                AttachmentPart(
                    attachment=Attachment(
                        type="image/png", url="https://example.com/i.png"
                    )
                )
            ],
        ),
        id="url-attachment",
    ),
    pytest.param(
        Message(role="system", parts=[TextPart(text="be brief")]),
        id="system",
    ),
]


@pytest.mark.parametrize("message", ROUND_TRIP_MESSAGES)
def test_ensure_message_round_trip(db, message):
    message_id = storage.ensure_message(db, message)
    loaded = storage.load_message(db, message_id)
    assert loaded.to_dict() == message.to_dict()


def test_message_hash_golden():
    # Golden hash: an accidental change to canonical serialization must
    # fail loudly rather than silently forking the dedupe space.
    message = Message(role="user", parts=[TextPart(text="hello")])
    canonical = '{"parts":[{"text":"hello","type":"text"}],"role":"user"}'
    import hashlib

    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert storage.message_hash(message) == expected


def test_message_hash_attachment_content_independent(tmp_path):
    # The same bytes via content= and via path= hash to the same message
    path = tmp_path / "blob.png"
    path.write_bytes(b"same bytes")
    m1 = Message(
        role="user",
        parts=[
            AttachmentPart(
                attachment=Attachment(type="image/png", content=b"same bytes")
            )
        ],
    )
    m2 = Message(
        role="user",
        parts=[AttachmentPart(attachment=Attachment(type="image/png", path=str(path)))],
    )
    assert storage.message_hash(m1) == storage.message_hash(m2)


def test_ensure_message_dedupes(db):
    m1 = Message(role="user", parts=[TextPart(text="same")])
    m2 = Message(role="user", parts=[TextPart(text="same")])
    id1 = storage.ensure_message(db, m1)
    id2 = storage.ensure_message(db, m2)
    assert id1 == id2
    assert db["messages"].count == 1
    assert db["parts"].count == 1


def test_ensure_message_distinct_for_different_roles(db):
    id1 = storage.ensure_message(db, Message(role="user", parts=[TextPart(text="x")]))
    id2 = storage.ensure_message(
        db, Message(role="assistant", parts=[TextPart(text="x")])
    )
    assert id1 != id2
    assert db["messages"].count == 2


def test_attachments_are_content_addressed(db):
    att = Attachment(type="image/png", content=b"shared bytes")
    m1 = Message(role="user", parts=[AttachmentPart(attachment=att)])
    m2 = Message(
        role="user",
        parts=[
            TextPart(text="again"),
            AttachmentPart(
                attachment=Attachment(type="image/png", content=b"shared bytes")
            ),
        ],
    )
    storage.ensure_message(db, m1)
    storage.ensure_message(db, m2)
    assert db["attachments"].count == 1


def test_ensure_node_dedupes_and_tracks_depth(db):
    mid1 = storage.ensure_message(db, Message(role="user", parts=[TextPart(text="a")]))
    mid2 = storage.ensure_message(
        db, Message(role="assistant", parts=[TextPart(text="b")])
    )
    root, created1 = storage.ensure_node(db, None, mid1)
    root_again, created2 = storage.ensure_node(db, None, mid1)
    assert root == root_again
    assert created1 is True
    assert created2 is False
    child, _ = storage.ensure_node(db, root, mid2)
    rows = {row["id"]: row for row in db["nodes"].rows}
    assert rows[root]["depth"] == 0
    assert rows[root]["parent_id"] is None
    assert rows[child]["depth"] == 1
    assert rows[child]["parent_id"] == root
    # Same message under a different parent is a different node
    other, _ = storage.ensure_node(db, child, mid1)
    assert other != root


def test_append_chain_returns_leaf_and_first_new(db):
    messages = [
        Message(role="system", parts=[TextPart(text="sys")]),
        Message(role="user", parts=[TextPart(text="q1")]),
    ]
    leaf, first_new = storage.append_chain(db, None, messages)
    assert first_new is not None
    path = storage.node_path(db, leaf)
    assert len(path) == 2
    assert [row["depth"] for row in path] == [0, 1]
    # Extending the same chain creates only the new nodes
    more = messages + [
        Message(role="assistant", parts=[TextPart(text="a1")]),
        Message(role="user", parts=[TextPart(text="q2")]),
    ]
    leaf2, first_new2 = storage.append_chain(db, None, more)
    assert db["nodes"].count == 4
    path2 = storage.node_path(db, leaf2)
    assert len(path2) == 4
    # first_new2 is the assistant message node at depth 2
    assert first_new2 == path2[2]["node_id"]
    # Replaying an identical chain creates nothing new
    leaf3, first_new3 = storage.append_chain(db, None, more)
    assert leaf3 == leaf2
    assert first_new3 is None
    assert db["nodes"].count == 4


def test_append_chain_forks_on_divergence(db):
    original = [
        Message(role="user", parts=[TextPart(text="q")]),
        Message(
            role="assistant", parts=[ReasoningPart(text="hmm"), TextPart(text="rich")]
        ),
    ]
    leaf1, _ = storage.append_chain(db, None, original)
    # A degraded echo of the assistant message forks at depth 1
    echoed = [
        Message(role="user", parts=[TextPart(text="q")]),
        Message(role="assistant", parts=[TextPart(text="rich")]),
    ]
    leaf2, first_new = storage.append_chain(db, None, echoed)
    assert leaf2 != leaf1
    path1 = storage.node_path(db, leaf1)
    path2 = storage.node_path(db, leaf2)
    # Shared prefix: same root node
    assert path1[0]["node_id"] == path2[0]["node_id"]
    # Siblings at depth 1
    assert path1[1]["node_id"] != path2[1]["node_id"]
    assert first_new == path2[1]["node_id"]
    assert db["nodes"].count == 3


def test_load_messages_for_path(db):
    messages = [
        Message(role="system", parts=[TextPart(text="sys")]),
        Message(role="user", parts=[TextPart(text="q")]),
        Message(role="assistant", parts=[TextPart(text="a")]),
    ]
    leaf, _ = storage.append_chain(db, None, messages)
    path = storage.node_path(db, leaf)
    loaded = storage.load_messages(db, [row["message_id"] for row in path])
    assert [m.to_dict() for m in loaded] == [m.to_dict() for m in messages]


def test_duplicate_message_at_two_positions(db):
    # "ok" twice in a row: two nodes, one message row
    messages = [
        Message(role="user", parts=[TextPart(text="ok")]),
        Message(role="assistant", parts=[TextPart(text="ok")]),
        Message(role="user", parts=[TextPart(text="ok")]),
    ]
    leaf, _ = storage.append_chain(db, None, messages)
    assert len(storage.node_path(db, leaf)) == 3
    assert db["nodes"].count == 3
    assert db["messages"].count == 2  # user "ok" deduped, assistant distinct


def test_instance_ids_recorded_on_insert(db):
    db["tool_instances"].insert(
        {"id": 7, "plugin": "p", "name": "n", "arguments": "{}"}
    )
    message = Message(
        role="tool",
        parts=[ToolResultPart(name="f", output="out", tool_call_id="call_9")],
    )
    storage.ensure_message(db, message, instance_ids={"call_9": 7})
    part = next(db["parts"].rows)
    assert part["instance_id"] == 7


def test_parts_table_typed_columns(db):
    message = Message(
        role="assistant",
        parts=[
            ReasoningPart(text="think", redacted=False),
            TextPart(text="body"),
            ToolCallPart(name="f", arguments={"a": 1}, tool_call_id="c1"),
        ],
    )
    storage.ensure_message(db, message)
    rows = list(db["parts"].rows_where(order_by='"order"'))
    assert [r["type"] for r in rows] == ["reasoning", "text", "tool_call"]
    assert rows[0]["text"] == "think"
    assert rows[1]["text"] == "body"
    assert rows[2]["name"] == "f"
    assert rows[2]["tool_call_id"] == "c1"
