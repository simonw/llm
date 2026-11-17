import asyncio
import time

import pytest

import llm


@pytest.mark.parametrize("first_reader", ["text", "events"])
@pytest.mark.parametrize("cached_reader", ["text", "events"])
def test_cached_response_preserves_timing(mock_model, first_reader, cached_reader):
    mock_model.enqueue(["hello", " world"])
    conversation = llm.get_model("mock").conversation()
    response = conversation.prompt("hello")
    completed = []
    response.on_done(completed.append)
    if first_reader == "text":
        assert list(response) == ["hello", " world"]
    else:
        list(response.stream_events())

    timing = (response.duration_ms(), response.datetime_utc())
    events = list(response.stream_events())
    assert timing[0] >= 0
    assert timing[1]
    for _ in range(2):
        time.sleep(0.01)
        if cached_reader == "text":
            assert list(response) == ["hello", " world"]
        else:
            assert list(response.stream_events()) == events
        assert response.text() == "hello world"
        assert response.usage() == llm.Usage(input=1, output=2)
        assert len(mock_model.history) == 1
        assert conversation.responses == [response]
        assert completed == [response]
        assert (response.duration_ms(), response.datetime_utc()) == timing


@pytest.mark.asyncio
@pytest.mark.parametrize("first_reader", ["text", "events"])
@pytest.mark.parametrize("cached_reader", ["text", "events"])
async def test_cached_async_response_preserves_timing(
    async_mock_model, first_reader, cached_reader
):
    async_mock_model.enqueue(["hello", " world"])
    conversation = llm.get_async_model("mock").conversation()
    response = conversation.prompt("hello")
    completed = []
    await response.on_done(completed.append)
    if first_reader == "text":
        assert [chunk async for chunk in response] == ["hello", " world"]
    else:
        [event async for event in response.astream_events()]

    timing = (await response.duration_ms(), await response.datetime_utc())
    events = [event async for event in response.astream_events()]
    assert timing[0] >= 0
    assert timing[1]
    for _ in range(2):
        await asyncio.sleep(0.01)
        if cached_reader == "text":
            assert [chunk async for chunk in response] == ["hello", " world"]
        else:
            assert [event async for event in response.astream_events()] == events
        assert await response.text() == "hello world"
        assert await response.usage() == llm.Usage(input=1, output=2)
        assert len(async_mock_model.history) == 1
        assert conversation.responses == [response]
        assert completed == [response]
        assert (await response.duration_ms(), await response.datetime_utc()) == timing
