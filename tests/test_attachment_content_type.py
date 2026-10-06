import pytest

import llm


@pytest.mark.parametrize(
    "content_type",
    ["image/png; charset=utf-8", "IMAGE/PNG", " image/png ; name=preview.png"],
)
def test_url_attachment_media_type_parameters(httpx2_mock, mock_model, content_type):
    url = "https://images.example/preview.png"
    httpx2_mock.add_response(
        method="HEAD", url=url, headers={"Content-Type": content_type}
    )
    mock_model.enqueue(["two boxes"])
    response = mock_model.prompt("describe file", attachments=[llm.Attachment(url=url)])
    assert response.text() == "two boxes"


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ("audio/wave; rate=44100", "audio/wav"),
        ("application/octet-stream", "application/octet-stream"),
        (None, None),
    ],
)
def test_url_attachment_resolve_type(httpx2_mock, content_type, expected):
    url = "https://files.example/sample"
    headers = {} if content_type is None else {"Content-Type": content_type}
    httpx2_mock.add_response(method="HEAD", url=url, headers=headers)
    assert llm.Attachment(url=url).resolve_type() == expected
