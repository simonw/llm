import pytest


@pytest.mark.asyncio
async def test_async_model(async_mock_model):
    gathered = []
    async_mock_model.enqueue(["hello world"])
    async for chunk in async_mock_model.prompt("hello"):
        gathered.append(chunk)
    assert gathered == ["hello world"]
