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


def test_attachment_content_bytes_follows_redirects(httpx_mock):
    httpx_mock.add_response(
        url="https://example.com/redirected.png",
        status_code=301,
        headers={"Location": "https://example.com/actual.png"},
    )
    httpx_mock.add_response(
        url="https://example.com/actual.png",
        content=TINY_PNG,
    )
    attachment = llm.Attachment(url="https://example.com/redirected.png")
    assert attachment.content_bytes() == TINY_PNG


def test_attachment_content_bytes_limits_redirects(httpx_mock):
    for redirect in range(4):
        httpx_mock.add_response(
            url=f"https://example.com/redirect-{redirect}",
            status_code=301,
            headers={"Location": f"https://example.com/redirect-{redirect + 1}"},
        )

    attachment = llm.Attachment(url="https://example.com/redirect-0")
    with pytest.raises(httpx2.TooManyRedirects):
        attachment.content_bytes()

    assert len(httpx_mock.get_requests()) == 4


def test_attachment_resolve_type_follows_redirects(httpx_mock):
    httpx_mock.add_response(
        method="HEAD",
        url="https://example.com/redirected.png",
        status_code=301,
        headers={"Location": "https://example.com/actual.png"},
    )
    httpx_mock.add_response(
        method="HEAD",
        url="https://example.com/actual.png",
        headers={"content-type": "image/png"},
    )
    attachment = llm.Attachment(url="https://example.com/redirected.png")
    assert attachment.resolve_type() == "image/png"


def test_attachment_resolve_type_limits_redirects(httpx_mock):
    for redirect in range(4):
        httpx_mock.add_response(
            method="HEAD",
            url=f"https://example.com/redirect-{redirect}",
            status_code=301,
            headers={"Location": f"https://example.com/redirect-{redirect + 1}"},
        )

    attachment = llm.Attachment(url="https://example.com/redirect-0")
    with pytest.raises(httpx2.TooManyRedirects):
        attachment.resolve_type()

    assert len(httpx_mock.get_requests()) == 4
