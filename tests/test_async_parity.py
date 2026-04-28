"""Async parity: every sync API must work the same
way on AsyncResponse and AsyncConversation.

Uses the llm-echo plugin (sync ``Echo`` + async ``EchoAsync``) so both
paths exercise real registered models with identical behaviour.
"""

import json

import llm
import pytest

# ---- basic sanity: both variants are registered --------------------


def test_echo_registered_for_both():
    assert isinstance(llm.get_model("echo"), llm.Model)
    assert isinstance(llm.get_async_model("echo"), llm.AsyncModel)


# ---- AsyncResponse.to_dict / from_dict -----------------------------


@pytest.mark.asyncio
async def test_async_to_dict_captures_chain_and_output():
    model = llm.get_async_model("echo")
    r = model.prompt("hello")
    await r.text()

    d = r.to_dict()
    assert d["model"] == "echo"
    assert d["prompt"]["messages"] == [llm.user("hello").to_dict()]
    # Echo's output is JSON describing the input; it's the assistant's text.
    assert len(d["messages"]) == 1
    assert d["messages"][0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_async_to_dict_raises_before_awaited():
    model = llm.get_async_model("echo")
    r = model.prompt("hello")
    with pytest.raises(ValueError):
        r.to_dict()


@pytest.mark.asyncio
async def test_async_from_dict_rehydrates():
    model = llm.get_async_model("echo")
    r = model.prompt("hello")
    await r.text()

    payload = json.dumps(r.to_dict())
    restored = llm.AsyncResponse.from_dict(json.loads(payload))

    assert restored._done
    # text_or_raise should match (same text as original)
    assert restored.text_or_raise() == r.text_or_raise()
    # messages structure preserved
    assert await restored.messages() == await r.messages()
    # prompt.messages (the chain that was sent) preserved
    assert restored.prompt.messages == r.prompt.messages


@pytest.mark.asyncio
async def test_async_from_dict_then_reply_continues():
    """The whole point: persist an async response across process
    boundary (via JSON), rehydrate, continue with reply()."""
    model = llm.get_async_model("echo")
    r1 = model.prompt("q1")
    await r1.text()

    payload = json.dumps(r1.to_dict())
    restored = llm.AsyncResponse.from_dict(json.loads(payload))

    r2 = await restored.reply("q2")
    await r2.text()

    # r2 was sent the full chain including r1's output.
    chain_roles = [m.role for m in r2.prompt.messages]
    assert chain_roles == ["user", "assistant", "user"]
    assert r2.prompt.messages[0].parts[0].text == "q1"
    assert r2.prompt.messages[-1].parts[0].text == "q2"


# ---- AsyncResponse rehydrated via from_row (SQLite path) -----------


@pytest.mark.asyncio
async def test_async_from_row_response_messages_synthesized(tmp_path):
    """SQLite rehydrate for async responses must populate
    response.messages from _chunks+_tool_calls so follow-up chains
    don't silently drop the assistant turn."""
    import sqlite_utils
    from llm.migrations import migrate

    model = llm.get_async_model("echo")
    r = model.prompt("hello")
    await r.text()

    db = sqlite_utils.Database(str(tmp_path / "logs.db"))
    migrate(db)
    # to_sync_response is what log_to_db uses for async.
    sync_r = await r.to_sync_response()
    sync_r.log_to_db(db)

    row = next(db["responses"].rows)
    rehydrated = llm.AsyncResponse.from_row(db, row)

    assert rehydrated._stream_events == []
    # response.messages falls back to _chunks — must not be empty.
    msgs = await rehydrated.messages()
    assert len(msgs) == 1
    assert msgs[0].role == "assistant"
    assert isinstance(msgs[0].parts[0], llm.parts.TextPart)


# ---- AsyncConversation follow-up via load_conversation -------------


@pytest.mark.asyncio
async def test_async_load_conversation_follow_up_preserves_chain(tmp_path):
    """Async equivalent of the llm -c regression: after log_to_db +
    load_conversation, a follow-up turn's prompt.messages is the full
    [user, assistant, user] chain — not missing the assistant."""
    import sqlite_utils
    from llm.cli import load_conversation
    from llm.migrations import migrate

    model = llm.get_async_model("echo")
    r1 = model.prompt("q1")
    await r1.text()

    db_path = tmp_path / "logs.db"
    db = sqlite_utils.Database(str(db_path))
    migrate(db)
    (await r1.to_sync_response()).log_to_db(db)

    conv = load_conversation(None, async_=True, database=str(db_path))
    r2 = conv.prompt("q2")
    await r2.text()

    chain = r2.prompt.messages
    assert [m.role for m in chain] == ["user", "assistant", "user"]
    assert chain[0].parts[0].text == "q1"
    assert chain[-1].parts[0].text == "q2"


# ---- Sync/async semantic parity for reply()+to_dict() --------------


def _capture_sync(model):
    r1 = model.prompt("ping")
    r1.text()
    payload1 = json.dumps(r1.to_dict())
    restored = llm.Response.from_dict(json.loads(payload1))
    r2 = restored.reply("pong")
    r2.text()
    return r2.prompt.messages


async def _capture_async(model):
    r1 = model.prompt("ping")
    await r1.text()
    payload1 = json.dumps(r1.to_dict())
    restored = llm.AsyncResponse.from_dict(json.loads(payload1))
    r2 = await restored.reply("pong")
    await r2.text()
    return r2.prompt.messages


@pytest.mark.asyncio
async def test_sync_and_async_produce_identical_chain():
    """Run the full save → restore → reply loop against sync Echo and
    async EchoAsync. The chain sent on the second turn must be
    structurally identical."""
    sync_chain = _capture_sync(llm.get_model("echo"))
    async_chain = await _capture_async(llm.get_async_model("echo"))

    # Echo's assistant output differs between invocations only in
    # the "previous" field — but for the first turn both see empty
    # previous, so outputs match.
    sync_dicts = [m.to_dict() for m in sync_chain]
    async_dicts = [m.to_dict() for m in async_chain]
    assert sync_dicts == async_dicts


# ---- AsyncChainResponse tool-result turn pre-bakes chain -----------


@pytest.mark.asyncio
async def test_async_chain_tool_result_turn_has_full_chain():
    """AsyncChainResponse must pre-bake the full chain on tool-result
    turns, same as sync ChainResponse."""

    async def my_tool(x: int) -> int:
        "Double the input."
        return x * 2

    model = llm.get_async_model("echo")
    # Drive a one-iteration chain by asking echo to emit a tool call
    # (echo's JSON-prompt syntax).
    chain = model.chain(
        json.dumps(
            {
                "tool_calls": [{"name": "my_tool", "arguments": {"x": 5}}],
                "prompt": "prompt",
            }
        ),
        tools=[llm.Tool.function(my_tool, name="my_tool")],
    )

    responses = []
    async for response in chain.responses():
        responses.append(response)

    # Two responses: the tool-call turn and the tool-result turn.
    assert len(responses) == 2
    second = responses[1]
    # Second turn's prompt.messages includes the prior turn (user +
    # assistant with tool call) plus a tool-role message with the result.
    chain_roles = [m.role for m in second.prompt.messages]
    assert "tool" in chain_roles
    assert chain_roles[0] == "user"


# ---- astream_events() parity with stream_events() ------------------


@pytest.mark.asyncio
async def test_astream_events_matches_stream_events_for_text_only():
    """Echo yields plain str (legacy plugin). Both sync and async
    paths should wrap those into StreamEvent(type='text') with the
    same shape."""
    sync_model = llm.get_model("echo")
    async_model = llm.get_async_model("echo")

    sync_r = sync_model.prompt("hello")
    sync_events = list(sync_r.stream_events())

    async_r = async_model.prompt("hello")
    async_events = []
    async for ev in async_r.astream_events():
        async_events.append(ev)

    # Same event types, same payload.
    assert [e.type for e in sync_events] == [e.type for e in async_events]
    assert all(e.type == "text" for e in sync_events)
    assert "".join(e.chunk for e in sync_events) == "".join(
        e.chunk for e in async_events
    )


# ---- Async reply chaining --------------------------------------------


# ---- Additional edge cases ----------------------------------------


@pytest.mark.asyncio
async def test_async_from_dict_model_override():
    model = llm.get_async_model("echo")
    r = model.prompt("hi")
    await r.text()
    payload = json.dumps(r.to_dict())

    # Pass model explicitly to override whatever's in the payload.
    alt = llm.get_async_model("echo")
    restored = llm.AsyncResponse.from_dict(json.loads(payload), model=alt)
    assert restored.model is alt


def test_sync_from_dict_model_override():
    model = llm.get_model("echo")
    r = model.prompt("hi")
    r.text()
    payload = json.dumps(r.to_dict())

    alt = llm.get_model("echo")
    restored = llm.Response.from_dict(json.loads(payload), model=alt)
    assert restored.model is alt


@pytest.mark.asyncio
async def test_async_to_dict_preserves_datetime():
    model = llm.get_async_model("echo")
    r = model.prompt("hi")
    await r.text()
    d = r.to_dict()
    assert "datetime_utc" in d
    assert isinstance(d["datetime_utc"], str)


@pytest.mark.asyncio
async def test_async_to_dict_preserves_usage_when_set(async_mock_model):
    """When a plugin calls response.set_usage, to_dict captures it.
    async_mock_model does set usage; llm-echo's async variant doesn't."""
    async_mock_model.enqueue(["ok"])
    r = async_mock_model.prompt("hi")
    await r.text()
    d = r.to_dict()
    assert "usage" in d
    assert d["usage"]["input"] is not None
    assert d["usage"]["output"] is not None

    # And it round-trips.
    restored = llm.AsyncResponse.from_dict(d, model=async_mock_model)
    assert restored.input_tokens == d["usage"]["input"]
    assert restored.output_tokens == d["usage"]["output"]


@pytest.mark.asyncio
async def test_async_reply_messages_kwarg_appends():
    """AsyncResponse.reply(messages=[...]) appends extra messages onto
    the chain in place of a trailing user string (mirrors sync test)."""
    model = llm.get_async_model("echo")
    r1 = model.prompt("q1")
    await r1.text()
    r2 = await r1.reply(messages=[llm.user("extra")])
    await r2.text()
    assert [m.role for m in r2.prompt.messages] == ["user", "assistant", "user"]
    assert r2.prompt.messages[-1].parts[0].text == "extra"


@pytest.mark.asyncio
async def test_async_full_chain_to_dict_round_trip_three_turns():
    """Serialize on turn 3 — chain must include q1, a1, q2, a2, q3 on
    round-trip."""
    model = llm.get_async_model("echo")
    r1 = model.prompt("q1")
    await r1.text()
    r2 = await r1.reply("q2")
    await r2.text()
    r3 = await r2.reply("q3")
    await r3.text()

    payload = json.dumps(r3.to_dict())
    restored = llm.AsyncResponse.from_dict(json.loads(payload))
    assert [m.role for m in restored.prompt.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    texts = [m.parts[0].text for m in restored.prompt.messages if m.parts]
    assert texts[0] == "q1"
    assert texts[2] == "q2"
    assert texts[4] == "q3"

    # And continuing from the restored response extends the chain.
    r4 = await restored.reply("q4")
    await r4.text()
    assert [m.role for m in r4.prompt.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]


@pytest.mark.asyncio
async def test_async_reply_chains_three_turns():
    model = llm.get_async_model("echo")
    r1 = model.prompt("q1")
    await r1.text()
    r2 = await r1.reply("q2")
    await r2.text()
    r3 = await r2.reply("q3")
    await r3.text()

    chain = r3.prompt.messages
    assert [m.role for m in chain] == ["user", "assistant", "user", "assistant", "user"]
    texts = [m.parts[0].text for m in chain if m.parts]
    assert texts[0] == "q1"
    assert texts[2] == "q2"
    assert texts[4] == "q3"
