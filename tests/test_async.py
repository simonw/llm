import llm
import pytest


@pytest.mark.asyncio
async def test_async_model(async_mock_model):
    gathered = []
    async_mock_model.enqueue(["hello world"])
    async for chunk in async_mock_model.prompt("hello"):
        gathered.append(chunk)
    assert gathered == ["hello world"]
    # Not as an iterator
    async_mock_model.enqueue(["hello world"])
    response = await async_mock_model.prompt("hello")
    text = await response.text()
    assert text == "hello world"
    assert isinstance(response, llm.AsyncResponse)
    usage = await response.usage()
    assert usage.input == 1
    assert usage.output == 1
    assert usage.details is None


@pytest.mark.asyncio
async def test_async_model_conversation(async_mock_model):
    async_mock_model.enqueue(["joke 1"])
    conversation = async_mock_model.conversation()
    response = await conversation.prompt("joke")
    text = await response.text()
    assert text == "joke 1"
    async_mock_model.enqueue(["joke 2"])
    response2 = await conversation.prompt("again")
    text2 = await response2.text()
    assert text2 == "joke 2"
