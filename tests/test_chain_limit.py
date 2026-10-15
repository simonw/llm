import json

import pytest
import llm


def test_chain_limit_allows_final_response_at_limit():
    """A chain that finishes on turn N must not raise when chain_limit is N."""

    def f(x: str) -> str:
        return "got:" + x

    model = llm.get_model("echo")
    conversation = model.conversation(tools=[f])
    text = conversation.chain("hi", chain_limit=1, stream=False).text()
    assert '"prompt": "hi"' in text


def test_chain_limit_raises_when_tools_would_continue():
    """A tool call on turn N with chain_limit=N must raise before turn N+1."""

    def f(x: str) -> str:
        return "got:" + x

    model = llm.get_model("echo")
    conversation = model.conversation(tools=[f])
    payload = json.dumps(
        {"prompt": "hi", "tool_calls": [{"name": "f", "arguments": {"x": "a"}}]}
    )
    with pytest.raises(ValueError, match="Chain limit of 1 exceeded"):
        conversation.chain(payload, chain_limit=1, stream=False).text()


@pytest.mark.asyncio
async def test_async_chain_limit_allows_final_response_at_limit():
    def f(x: str) -> str:
        return "got:" + x

    model = llm.get_async_model("echo")
    conversation = model.conversation(tools=[f])
    text = await conversation.chain("hi", chain_limit=1, stream=False).text()
    assert '"prompt": "hi"' in text


@pytest.mark.asyncio
async def test_async_chain_limit_raises_when_tools_would_continue():
    def f(x: str) -> str:
        return "got:" + x

    model = llm.get_async_model("echo")
    conversation = model.conversation(tools=[f])
    payload = json.dumps(
        {"prompt": "hi", "tool_calls": [{"name": "f", "arguments": {"x": "a"}}]}
    )
    with pytest.raises(ValueError, match="Chain limit of 1 exceeded"):
        await conversation.chain(payload, chain_limit=1, stream=False).text()
