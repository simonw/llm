import base64
import json
import os
import sys
from unittest.mock import ANY

import httpx2
import pytest
from click.testing import CliRunner

import llm
from llm import cli

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\xa6\x00\x00\x01\x1a"
    b"\x02\x03\x00\x00\x00\xe6\x99\xc4^\x00\x00\x00\tPLTE\xff\xff\xff"
    b"\x00\xff\x00\xfe\x01\x00\x12t\x01J\x00\x00\x00GIDATx\xda\xed\xd81\x11"
    b"\x000\x08\xc0\xc0.]\xea\xaf&Q\x89\x04V\xe0>\xf3+\xc8\x91Z\xf4\xa2\x08EQ\x14E"
    b"Q\x14EQ\x14EQ\xd4B\x91$I3\xbb\xbf\x08EQ\x14EQ\x14EQ\x14E\xd1\xa5"
    b"\xd4\x17\x91\xc6\x95\x05\x15\x0f\x9f\xc5\t\x9f\xa4\x00\x00\x00\x00IEND\xaeB`"
    b"\x82"
)

TINY_WAV = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00"


@pytest.fixture(params=["content", "path", "url"])
def legacy_attachment_history(request, db_factory, tmp_path):
    from llm.migrations import migrate

    db_path = tmp_path / "legacy-attachments.db"
    db = db_factory(str(db_path))
    migrate(db)
    conversation_id = "01aaaaaaaaaaaaaaaaaaaaaaaa"
    image_response_id = "01cccccccccccccccccccccccc"
    db["conversations"].insert(
        {"id": conversation_id, "name": "Legacy images", "model": "mock"}
    )
    for response_id, prompt, response in (
        ("01bbbbbbbbbbbbbbbbbbbbbbbb", "Hello", "Hi"),
        (image_response_id, "Describe these images", "Two images"),
    ):
        db["responses"].insert(
            {
                "id": response_id,
                "model": "mock",
                "prompt": prompt,
                "system": None,
                "prompt_json": None,
                "options_json": "{}",
                "response": response,
                "response_json": None,
                "conversation_id": conversation_id,
                "duration_ms": 1,
                "datetime_utc": "2025-01-01T00:00:00+00:00",
                "schema_id": None,
            }
        )

    if request.param == "path":
        path = tmp_path / "tiny.png"
        path.write_bytes(TINY_PNG)
        primary = llm.Attachment(type="image/png", path=str(path))
    elif request.param == "url":
        primary = llm.Attachment(type="image/png", url="https://example.com/tiny.png")
    else:
        primary = llm.Attachment(type="image/png", content=TINY_PNG)
    attachments = [
        primary,
        llm.Attachment(type="image/jpeg", url="https://example.com/second.jpg"),
    ]
    # Insert in reverse order so the test exercises prompt_attachments.order.
    for order in reversed(range(len(attachments))):
        attachment = attachments[order]
        db["attachments"].insert(
            {
                "id": attachment.id(),
                "type": attachment.type,
                "path": attachment.path,
                "url": attachment.url,
                "content": attachment.content,
            }
        )
        db["prompt_attachments"].insert(
            {
                "response_id": image_response_id,
                "attachment_id": attachment.id(),
                "order": order,
            }
        )
    return db, db_path, conversation_id, image_response_id, attachments


@pytest.mark.parametrize("async_", [False, True], ids=["sync", "async"])
def test_legacy_response_restores_prompt_attachments(
    legacy_attachment_history, mock_model, async_mock_model, async_
):
    db, _, _, response_id, attachments = legacy_attachment_history
    before = {table: list(db[table].rows) for table in db.table_names()}
    response_class = llm.AsyncResponse if async_ else llm.Response
    response = response_class.from_row(db, db["responses"].get(response_id))

    # Keep the legacy response attribute, and restore the canonical prompt too.
    assert response.attachments == attachments
    assert response.prompt.attachments == attachments
    expected = llm.user("Describe these images", *attachments)
    assert response.prompt.messages == [expected]
    # Both content bytes and path/URL references survive JSON serialization.
    serialized = json.loads(json.dumps(response.to_dict()))
    assert serialized["prompt"]["messages"] == [expected.to_dict()]
    round_trip = llm.Message.from_dict(serialized["prompt"]["messages"][0])
    assert round_trip.to_dict() == expected.to_dict()
    primary = round_trip.parts[1].attachment
    if not primary.url:
        assert primary.content_bytes() == TINY_PNG
    assert {table: list(db[table].rows) for table in db.table_names()} == before


@pytest.mark.parametrize("async_", [False, True], ids=["sync", "async"])
def test_legacy_continuation_serializes_ordered_attachments(
    legacy_attachment_history, mock_model, async_mock_model, async_
):
    from llm.default_plugins.openai_models import Chat

    db, db_path, conversation_id, _, attachments = legacy_attachment_history
    before = {table: list(db[table].rows) for table in db.table_names()}
    conversation = cli.load_conversation(
        conversation_id, async_=async_, database=str(db_path)
    )
    response = conversation.prompt("What colors are they?")
    # Render the actual continued chain through the provider adapter, without
    # executing the model or fetching the URL attachments.
    messages = Chat("offline-vision", vision=True).build_messages(
        response.prompt, conversation
    )
    primary_url = attachments[0].url or (
        "data:image/png;base64," + base64.b64encode(TINY_PNG).decode("ascii")
    )
    assert messages == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe these images"},
                {"type": "image_url", "image_url": {"url": primary_url}},
                {"type": "image_url", "image_url": {"url": attachments[1].url}},
            ],
        },
        {"role": "assistant", "content": "Two images"},
        {"role": "user", "content": "What colors are they?"},
    ]
    assert {table: list(db[table].rows) for table in db.table_names()} == before


@pytest.mark.parametrize(
    "attachment_type,attachment_content",
    [
        ("image/png", TINY_PNG),
        ("audio/wav", TINY_WAV),
    ],
)
def test_prompt_attachment(mock_model, logs_db, attachment_type, attachment_content):
    runner = CliRunner()
    mock_model.enqueue(["two boxes"])
    result = runner.invoke(
        cli.cli,
        ["prompt", "-m", "mock", "describe file", "-a", "-"],
        input=attachment_content,
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert result.output == "two boxes\n"
    assert mock_model.history[0][0].attachments[0] == llm.Attachment(
        type=attachment_type, path=None, url=None, content=attachment_content, _id=ANY
    )

    # Check it was logged correctly
    threads = list(logs_db["threads"].rows)
    assert len(threads) == 1
    assert threads[0]["name"] == "describe file"
    turn = next(iter(logs_db["turns"].rows))
    assert turn["model"] == "mock"
    attachment = next(iter(logs_db["attachments"].rows))
    assert attachment == {
        "id": ANY,
        "type": attachment_type,
        "path": None,
        "url": None,
        "content": attachment_content,
    }
    # The attachment hangs off a part of the stored user message
    part_attachment = next(iter(logs_db["part_attachments"].rows))
    assert part_attachment["attachment_id"] == attachment["id"]


def _count_open_fds():
    """Count open file descriptors (macOS and Linux only)."""
    if sys.platform == "darwin":
        fd_dir = "/dev/fd"
    elif sys.platform == "linux":
        fd_dir = "/proc/self/fd"
    else:
        return None
    return len(os.listdir(fd_dir))


@pytest.mark.skipif(
    sys.platform not in ("darwin", "linux"),
    reason="File descriptor counting only supported on macOS and Linux",
)
def test_attachment_no_file_descriptor_leak(tmp_path):
    """Verify reading attachments from paths doesn't leak file descriptors."""
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(b"x" * 1000)

    # Warm up - first call may open other resources
    attachment = llm.Attachment(path=str(test_file))
    _ = attachment.id()
    _ = attachment.content_bytes()

    baseline = _count_open_fds()

    # Create many attachments and read them
    for _ in range(100):
        a = llm.Attachment(path=str(test_file))
        _ = a.id()
        _ = a.content_bytes()

    # File descriptor count should not have grown significantly
    assert _count_open_fds() <= baseline + 5


def test_attachment_content_bytes_follows_redirects(httpx2_mock):
    httpx2_mock.add_response(
        url="https://example.com/redirected.png",
        status_code=301,
        headers={"Location": "https://example.com/actual.png"},
    )
    httpx2_mock.add_response(
        url="https://example.com/actual.png",
        content=TINY_PNG,
    )
    attachment = llm.Attachment(url="https://example.com/redirected.png")
    assert attachment.content_bytes() == TINY_PNG


def test_attachment_content_bytes_limits_redirects(httpx2_mock):
    for redirect in range(4):
        httpx2_mock.add_response(
            url=f"https://example.com/redirect-{redirect}",
            status_code=301,
            headers={"Location": f"https://example.com/redirect-{redirect + 1}"},
        )

    attachment = llm.Attachment(url="https://example.com/redirect-0")
    with pytest.raises(httpx2.TooManyRedirects):
        attachment.content_bytes()

    assert len(httpx2_mock.get_requests()) == 4


def test_attachment_resolve_type_follows_redirects(httpx2_mock):
    httpx2_mock.add_response(
        method="HEAD",
        url="https://example.com/redirected.png",
        status_code=301,
        headers={"Location": "https://example.com/actual.png"},
    )
    httpx2_mock.add_response(
        method="HEAD",
        url="https://example.com/actual.png",
        headers={"content-type": "image/png"},
    )
    attachment = llm.Attachment(url="https://example.com/redirected.png")
    assert attachment.resolve_type() == "image/png"


def test_attachment_resolve_type_limits_redirects(httpx2_mock):
    for redirect in range(4):
        httpx2_mock.add_response(
            method="HEAD",
            url=f"https://example.com/redirect-{redirect}",
            status_code=301,
            headers={"Location": f"https://example.com/redirect-{redirect + 1}"},
        )

    attachment = llm.Attachment(url="https://example.com/redirect-0")
    with pytest.raises(httpx2.TooManyRedirects):
        attachment.resolve_type()

    assert len(httpx2_mock.get_requests()) == 4


UNSUPPORTED_ATTACHMENT_CASES = (
    ((), "This model does not support attachments"),
    (
        ("audio/wav",),
        "This model does not support attachments of type 'image/png', only audio/wav",
    ),
)


@pytest.mark.parametrize(
    "attachment_types,expected_message", UNSUPPORTED_ATTACHMENT_CASES
)
def test_conversation_prompt_rejects_unsupported_attachment_before_execute(
    mock_model, attachment_types, expected_message
):
    mock_model.attachment_types = frozenset(attachment_types)
    mock_model.enqueue(["sent"])
    conversation = mock_model.conversation()
    attachment = llm.Attachment(type="image/png", content=TINY_PNG)

    with pytest.raises(ValueError) as ex:
        conversation.prompt("describe", attachments=[attachment]).text()

    assert str(ex.value) == expected_message
    assert mock_model.history == []
    assert conversation.responses == []


@pytest.mark.parametrize(
    "attachment_types,expected_message", UNSUPPORTED_ATTACHMENT_CASES
)
@pytest.mark.asyncio
async def test_async_conversation_prompt_rejects_unsupported_attachment_before_execute(
    async_mock_model, attachment_types, expected_message
):
    async_mock_model.attachment_types = frozenset(attachment_types)
    async_mock_model.enqueue(["sent"])
    conversation = async_mock_model.conversation()
    attachment = llm.Attachment(type="image/png", content=TINY_PNG)

    with pytest.raises(ValueError) as ex:
        await conversation.prompt("describe", attachments=[attachment]).text()

    assert str(ex.value) == expected_message
    assert async_mock_model.history == []
    assert conversation.responses == []


def test_conversation_prompt_preserves_supported_attachment_in_follow_up_chain(
    mock_model,
):
    mock_model.enqueue(["describe"])
    mock_model.enqueue(["follow up"])
    conversation = mock_model.conversation()
    attachment = llm.Attachment(type="image/png", content=TINY_PNG)

    assert (
        conversation.prompt("describe", attachments=[attachment]).text() == "describe"
    )
    assert conversation.prompt("follow up").text() == "follow up"

    assert mock_model.history[0][0].attachments == [attachment]
    assert mock_model.history[1][0].messages == [
        llm.Message(
            role="user",
            parts=[
                llm.parts.TextPart(text="describe"),
                llm.parts.AttachmentPart(attachment=attachment),
            ],
        ),
        llm.assistant("describe"),
        llm.user("follow up"),
    ]


@pytest.mark.asyncio
async def test_async_conversation_prompt_preserves_supported_attachment_in_follow_up_chain(
    async_mock_model,
):
    async_mock_model.attachment_types = frozenset({"image/png"})
    async_mock_model.enqueue(["describe"])
    async_mock_model.enqueue(["follow up"])
    conversation = async_mock_model.conversation()
    attachment = llm.Attachment(type="image/png", content=TINY_PNG)

    assert (
        await conversation.prompt("describe", attachments=[attachment]).text()
        == "describe"
    )
    assert await conversation.prompt("follow up").text() == "follow up"

    assert async_mock_model.history[0][0].attachments == [attachment]
    assert async_mock_model.history[1][0].messages == [
        llm.Message(
            role="user",
            parts=[
                llm.parts.TextPart(text="describe"),
                llm.parts.AttachmentPart(attachment=attachment),
            ],
        ),
        llm.assistant("describe"),
        llm.user("follow up"),
    ]
