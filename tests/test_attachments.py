from click.testing import CliRunner
from unittest.mock import ANY
import llm

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\xa6\x00\x00\x01\x1a"
    b"\x02\x03\x00\x00\x00\xe6\x99\xc4^\x00\x00\x00\tPLTE\xff\xff\xff"
    b"\x00\xff\x00\xfe\x01\x00\x12t\x01J\x00\x00\x00GIDATx\xda\xed\xd81\x11"
    b"\x000\x08\xc0\xc0.]\xea\xaf&Q\x89\x04V\xe0>\xf3+\xc8\x91Z\xf4\xa2\x08EQ\x14E"
    b"Q\x14EQ\x14EQ\xd4B\x91$I3\xbb\xbf\x08EQ\x14EQ\x14EQ\x14E\xd1\xa5"
    b"\xd4\x17\x91\xc6\x95\x05\x15\x0f\x9f\xc5\t\x9f\xa4\x00\x00\x00\x00IEND\xaeB`"
    b"\x82"
)


def test_prompt_image(mock_model, logs_db):
    runner = CliRunner()
    mock_model.enqueue(["two boxes"])
    result = runner.invoke(
        llm.cli.cli,
        ["prompt", "-m", "mock", "describe image", "-a", "-"],
        input=TINY_PNG,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == "two boxes\n"
    assert mock_model.history[0][0].attachments[0] == llm.Attachment(
        type="image/png", path=None, url=None, content=TINY_PNG, _id=ANY
    )

    # Check it was logged correctly
    conversations = list(logs_db["conversations"].rows)
    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation["model"] == "mock"
    assert conversation["name"] == "describe image"
    response = list(logs_db["responses"].rows)[0]
    attachment = list(logs_db["attachments"].rows)[0]
    assert attachment == {
        "id": ANY,
        "type": "image/png",
        "path": None,
        "url": None,
        "content": TINY_PNG,
    }
    prompt_attachment = list(logs_db["prompt_attachments"].rows)[0]
    assert prompt_attachment["attachment_id"] == attachment["id"]
    assert prompt_attachment["response_id"] == response["id"]
