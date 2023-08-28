from click.testing import CliRunner
from llm.cli import cli
import pytest


@pytest.mark.parametrize(
    "format_,expected",
    (
        ("json", "[5, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]\n"),
        (
            "base64",
            (
                "AACgQAAAoEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==\n"
            ),
        ),
        (
            "hex",
            (
                "0000a0400000a04000000000000000000000000000000000000000000"
                "000000000000000000000000000000000000000000000000000000000"
                "00000000000000\n"
            ),
        ),
        (
            "blob",
            (
                b"\x00\x00\xef\xbf\xbd@\x00\x00\xef\xbf\xbd@\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n"
            ).decode("utf-8"),
        ),
    ),
)
def test_embed_output_format(format_, expected):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["embed", "--format", format_, "-c", "hello world", "-m", "embed-demo"]
    )
    assert result.exit_code == 0
    assert result.output == expected
