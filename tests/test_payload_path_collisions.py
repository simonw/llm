import pytest

import llm
from llm.logs import LogStore, resolve_payload


@pytest.mark.parametrize("kind", ["string", "container", "list_index"])
def test_payload_round_trip_with_reordered_colliding_metadata(
    db_factory, mock_model, kind
):
    store = LogStore(db_factory(memory=True))
    flat = "flat signature " * 10
    nested = "nested signature " * 10
    if kind == "container":
        flat = {"signature": flat}
        nested = {"signature": nested}
    metadata = (
        {"a.0": flat, "a": [nested]}
        if kind == "list_index"
        else {"a.b": flat, "a": {"b": nested}}
    )
    turns = []
    for values in (metadata, dict(reversed(list(metadata.items())))):
        mock_model.enqueue(
            [
                llm.parts.StreamEvent(
                    type="reasoning", chunk="thinking", provider_metadata=values
                ),
                "ok",
            ]
        )
        response = mock_model.prompt("hi")
        response.text()
        response.response_json = {"flat": flat, "nested": nested}
        turns.append(store.log(response))
    tips = {store.db["turns"].get(turn)["tip_message_hash"] for turn in turns}
    assert len(tips) == 1  # Identical messages genuinely share the stored parts.
    for turn in turns:
        assert store.turn_response_json(turn) == {"flat": flat, "nested": nested}


def test_legacy_ambiguous_references_keep_existing_read_behavior():
    flat = "flat signature " * 10
    nested = "nested signature " * 10
    messages = [
        llm.assistant(
            llm.parts.ReasoningPart(
                text="thinking", provider_metadata={"a.b": flat, "a": {"b": nested}}
            )
        )
    ]
    # A payload written by the old implementation under this stored key order.
    old_payload = '{"value": {"$": "0.0.pm.a.b"}}'
    assert resolve_payload(old_payload, messages) == {"value": nested}
