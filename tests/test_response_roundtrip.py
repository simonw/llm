"""Round-trip contract tests for the node-tree persistence layer.

A logged response must be fully reconstructable: log_to_db() followed by
from_row() reproduces the same structure that Response.to_dict() /
Response.from_dict() round-trips — including reasoning parts, redacted
markers, provider_metadata and tool interleaving that the legacy
flattened columns could not represent.
"""

import json

import pytest
import sqlite_utils

import llm
from llm import Response
from llm.cli import load_conversation
from llm.migrations import migrate
from llm.parts import ReasoningPart, StreamEvent, ToolResultPart


@pytest.fixture
def db():
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    return db


def test_full_response_round_trip(db, mock_model):
    mock_model.enqueue(
        [
            StreamEvent(
                type="reasoning",
                chunk="let me think",
                provider_metadata={"signature": "sig123"},
            ),
            StreamEvent(type="text", chunk="The answer "),
            StreamEvent(type="text", chunk="is 4"),
        ]
    )
    response = mock_model.prompt("What is 2+2?", system="be brief")
    response.text()
    response.log_to_db(db)

    row = db["responses"].get(response.id)
    loaded = Response.from_row(db, row)
    assert loaded.to_dict() == response.to_dict()
    # The reasoning part and its provider_metadata survived
    parts = [p for m in loaded.messages() for p in m.parts]
    reasoning = [p for p in parts if isinstance(p, ReasoningPart)]
    assert len(reasoning) == 1
    assert reasoning[0].text == "let me think"
    assert reasoning[0].provider_metadata == {"signature": "sig123"}


def test_redacted_reasoning_round_trip(db, mock_model):
    mock_model.enqueue(
        [
            StreamEvent(type="reasoning", chunk="", redacted=True),
            StreamEvent(type="text", chunk="result"),
        ]
    )
    response = mock_model.prompt("hi")
    response.text()
    response.log_to_db(db)
    loaded = Response.from_row(db, db["responses"].get(response.id))
    assert loaded.to_dict() == response.to_dict()
    parts = [p for m in loaded.messages() for p in m.parts]
    assert any(isinstance(p, ReasoningPart) and p.redacted for p in parts)


def test_tool_chain_round_trip(db):
    model = llm.get_model("echo")

    def upper(text: str) -> str:
        "Convert to upper case"
        return text.upper()

    chain = model.chain(
        json.dumps({"tool_calls": [{"name": "upper", "arguments": {"text": "hi"}}]}),
        tools=[upper],
    )
    chain.text()
    responses = chain._responses
    assert len(responses) == 2
    for response in responses:
        response.log_to_db(db)

    loaded_second = Response.from_row(db, db["responses"].get(responses[1].id))
    assert loaded_second.to_dict() == responses[1].to_dict()
    # The second turn's input chain carries the full history including
    # the tool result
    chain_messages = loaded_second.prompt.messages
    tool_parts = [
        p for m in chain_messages for p in m.parts if isinstance(p, ToolResultPart)
    ]
    assert len(tool_parts) == 1
    assert tool_parts[0].output == "HI"
    # prompt.tool_results recovered for the current turn
    assert len(loaded_second.prompt.tool_results) == 1
    assert loaded_second.prompt.tool_results[0].output == "HI"


def test_linear_growth_across_turns(db, mock_model):
    conversation = mock_model.conversation()
    for i, reply in enumerate(["first", "second", "third"]):
        mock_model.enqueue([reply])
        response = conversation.prompt(f"question {i}")
        response.text()
        response.log_to_db(db)

    # 3 user + 3 assistant messages, each stored exactly once
    assert db["messages"].count == 6
    assert db["nodes"].count == 6
    rows = list(db["responses"].rows_where(order_by="id"))
    # Each turn records: full input chain leaf, its own new input start,
    # and its output leaf; the next turn's chain extends the previous
    # output leaf
    for i, row in enumerate(rows):
        assert row["input_node_id"] is not None
        assert row["first_input_node_id"] is not None
        assert row["output_node_id"] is not None
    node_depths = {r["id"]: r["depth"] for r in db["nodes"].rows}
    assert node_depths[rows[0]["input_node_id"]] == 0
    assert node_depths[rows[0]["output_node_id"]] == 1
    assert node_depths[rows[2]["input_node_id"]] == 4
    assert node_depths[rows[2]["output_node_id"]] == 5
    # Turn 3's chain passes through turn 1's nodes (shared, not copied)
    from llm import storage

    path = storage.node_path(db, rows[2]["output_node_id"])
    assert path[0]["node_id"] is not None
    assert len(path) == 6


def test_load_conversation_preserves_metadata(user_path, mock_model, logs_db):
    # The llm -c case: reasoning signatures must survive a process
    # boundary via the database
    conversation = mock_model.conversation()
    mock_model.enqueue(
        [
            StreamEvent(
                type="reasoning",
                chunk="step one",
                provider_metadata={"signature": "topsecret"},
            ),
            StreamEvent(type="text", chunk="done"),
        ]
    )
    response = conversation.prompt("solve it")
    response.text()
    response.log_to_db(logs_db)

    loaded = load_conversation(conversation.id, database=str(user_path / "logs.db"))
    assert len(loaded.responses) == 1
    output_parts = [p for m in loaded.responses[0]._messages_now() for p in m.parts]
    reasoning = [p for p in output_parts if isinstance(p, ReasoningPart)]
    assert reasoning[0].provider_metadata == {"signature": "topsecret"}
    # And the next turn's chain would include it
    chain = loaded._build_full_chain(
        prompt="next question",
        attachments=None,
        tool_results=None,
        explicit_messages=None,
    )
    chain_parts = [p for m in chain for p in m.parts]
    assert any(
        isinstance(p, ReasoningPart)
        and p.provider_metadata == {"signature": "topsecret"}
        for p in chain_parts
    )


def test_identical_replay_creates_no_new_rows(db, mock_model):
    mock_model.enqueue(["same answer"])
    response = mock_model.prompt("same question")
    response.text()
    response.log_to_db(db)
    messages_before = db["messages"].count
    nodes_before = db["nodes"].count

    mock_model.enqueue(["same answer"])
    response2 = mock_model.prompt("same question")
    response2.text()
    response2.log_to_db(db)

    assert db["messages"].count == messages_before
    assert db["nodes"].count == nodes_before
    assert db["responses"].count == 2
    # The replay added no new input - recorded as NULL first_input_node_id
    second_row = db["responses"].get(response2.id)
    assert second_row["first_input_node_id"] is None
