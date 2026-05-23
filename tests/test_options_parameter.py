"""Tests for the `options=` parameter on `.prompt()` and `.reply()`.

The `options={...}` dict form is the documented API; the `**kwargs` form
continues to work undocumented for backwards compatibility.
"""

import pytest


def test_prompt_with_options_dict(mock_model):
    mock_model.enqueue(["ok"])
    r = mock_model.prompt("q", options={"max_tokens": 42})
    r.text()
    assert r.prompt.options.max_tokens == 42
    assert r.to_dict()["prompt"].get("options") == {"max_tokens": 42}


def test_prompt_kwargs_still_work(mock_model):
    mock_model.enqueue(["ok"])
    r = mock_model.prompt("q", max_tokens=42)
    r.text()
    assert r.prompt.options.max_tokens == 42


def test_prompt_options_and_kwargs_merge(mock_model):
    # Non-overlapping keys merge cleanly — options= and kwargs both contribute
    mock_model.Options.model_rebuild()
    mock_model.enqueue(["ok"])
    # Only max_tokens exists on MockModel.Options — use it via options=.
    # Pass an empty options dict alongside a kwarg to confirm both paths coexist.
    r = mock_model.prompt("q", options={}, max_tokens=7)
    r.text()
    assert r.prompt.options.max_tokens == 7


def test_prompt_options_and_kwargs_conflict_raises(mock_model):
    mock_model.enqueue(["ok"])
    with pytest.raises(TypeError, match="both in options="):
        mock_model.prompt("q", options={"max_tokens": 1}, max_tokens=2)


def test_conversation_prompt_with_options_dict(mock_model):
    mock_model.enqueue(["ok"])
    convo = mock_model.conversation()
    r = convo.prompt("q", options={"max_tokens": 99})
    r.text()
    assert r.prompt.options.max_tokens == 99


def test_response_reply_with_options_dict(mock_model):
    mock_model.enqueue(["first"])
    mock_model.enqueue(["second"])
    r1 = mock_model.prompt("q1", options={"max_tokens": 5})
    r1.text()
    r2 = r1.reply("q2", options={"max_tokens": 17})
    r2.text()
    assert r2.prompt.options.max_tokens == 17


def test_response_reply_kwargs_still_work(mock_model):
    mock_model.enqueue(["first"])
    mock_model.enqueue(["second"])
    r1 = mock_model.prompt("q1", max_tokens=5)
    r1.text()
    r2 = r1.reply("q2", max_tokens=17)
    r2.text()
    assert r2.prompt.options.max_tokens == 17


@pytest.mark.asyncio
async def test_async_prompt_with_options_dict(async_mock_model):
    # AsyncMockModel inherits the empty base Options (extra="forbid"),
    # so pass an empty options dict — this verifies the parameter is
    # accepted and the empty-dict path works.
    async_mock_model.enqueue(["ok"])
    r = await async_mock_model.prompt("q", options={}).text()
    assert r == "ok"


@pytest.mark.asyncio
async def test_async_prompt_options_and_kwargs_conflict_raises(async_mock_model):
    import llm

    # Build an async model with a real Option field so we can collide them.
    class AsyncModelWithOption(llm.AsyncModel):
        model_id = "async-with-option"

        class Options(llm.Options):
            from typing import Optional as _Opt
            from pydantic import Field as _Field

            max_tokens: _Opt[int] = _Field(default=None)

        async def execute(self, prompt, stream, response, conversation):
            yield "ok"

    m = AsyncModelWithOption()
    with pytest.raises(TypeError, match="both in options="):
        await m.prompt("q", options={"max_tokens": 1}, max_tokens=2).text()
