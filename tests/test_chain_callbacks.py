import asyncio

import pytest

import llm


@pytest.mark.parametrize("async_", (False, True))
@pytest.mark.parametrize("stream_events", (False, True))
def test_chain_on_response_before_tools(
    mock_model, async_mock_model, monkeypatch, async_, stream_events
):
    events = []
    completed = []
    model = async_mock_model if async_ else mock_model
    monkeypatch.setattr(model, "supports_tools", True)

    def lookup():
        events.append("tool")
        return "found"

    def chunks(prompt, stream, response, conversation):
        if not prompt.tool_results:
            yield "Looking"
            response.add_tool_call(
                llm.ToolCall(name="lookup", arguments={}, tool_call_id="lookup-1")
            )
        else:
            yield "Found"
        response.set_usage(input=2, output=3)

    async def async_chunks(*args, **kwargs):
        for chunk in chunks(*args, **kwargs):
            yield chunk

    monkeypatch.setattr(model, "execute", async_chunks if async_ else chunks)
    chain = model.chain("Find it", tools=[lookup])

    def completed_response(response):
        assert response._done
        assert response.input_tokens == 2
        assert response.output_tokens == 3
        assert response._end is not None
        assert response.conversation.responses[-1] is response
        completed.append(response)
        events.append("response")

    chain.on_response(completed_response)

    if async_:

        async def async_completed(response):
            await asyncio.sleep(0)
            assert completed[-1] is response
            events.append("async callback")

        chain.on_response(async_completed)

        async def consume():
            if stream_events:
                return "".join(
                    [
                        event.chunk
                        async for event in chain.astream_events()
                        if event.type == "text"
                    ]
                )
            return await chain.text()

        output = asyncio.run(consume())
        assert events == [
            "response",
            "async callback",
            "tool",
            "response",
            "async callback",
        ]
    else:
        if stream_events:
            output = "".join(
                event.chunk for event in chain.stream_events() if event.type == "text"
            )
        else:
            output = chain.text()
        assert events == ["response", "tool", "response"]

    assert output == "Looking Found"
    assert completed == chain._responses


@pytest.mark.parametrize("async_", (False, True))
def test_chain_on_response_error_stops_before_tools(
    mock_model, async_mock_model, monkeypatch, async_
):
    model = async_mock_model if async_ else mock_model
    monkeypatch.setattr(model, "supports_tools", True)
    tools_called = []

    def lookup():
        tools_called.append(True)
        return "found"

    def chunks(prompt, stream, response, conversation):
        yield "Looking"
        response.add_tool_call(llm.ToolCall(name="lookup", arguments={}))

    async def async_chunks(*args, **kwargs):
        for chunk in chunks(*args, **kwargs):
            yield chunk

    monkeypatch.setattr(model, "execute", async_chunks if async_ else chunks)
    chain = model.chain("Find it", tools=[lookup])

    def fail(response):
        raise RuntimeError("Could not save response")

    chain.on_response(fail)
    with pytest.raises(RuntimeError, match="Could not save response"):
        if async_:
            asyncio.run(chain.text())
        else:
            chain.text()
    assert tools_called == []
