from click.testing import CliRunner
from llm.cli import cli
import json
import pytest
import sqlite_utils


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


@pytest.mark.parametrize(
    "args,expected_error",
    ((["-c", "Content", "stories"], "Must provide both collection and id"),),
)
def test_embed_errors(args, expected_error):
    runner = CliRunner()
    result = runner.invoke(cli, ["embed"] + args)
    assert result.exit_code == 1
    assert expected_error in result.output


def test_embed_store(user_path):
    embeddings_db = user_path / "embeddings.db"
    assert not embeddings_db.exists()
    runner = CliRunner()
    result = runner.invoke(cli, ["embed", "-c", "hello", "-m", "embed-demo"])
    assert result.exit_code == 0
    # Should not have created the table
    assert not embeddings_db.exists()
    # Now run it to store
    result = runner.invoke(
        cli, ["embed", "-c", "hello", "-m", "embed-demo", "items", "1"]
    )
    assert result.exit_code == 0
    assert embeddings_db.exists()
    # Check the contents
    db = sqlite_utils.Database(str(embeddings_db))
    assert list(db["collections"].rows) == [
        {"id": 1, "name": "items", "model": "embed-demo"}
    ]
    assert list(db["embeddings"].rows) == [
        {
            "collection_id": 1,
            "id": "1",
            "embedding": (
                b"\x00\x00\xa0@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00"
            ),
            "content": None,
            "metadata": None,
        }
    ]
    # Should show up in 'llm embed-db collections'
    for is_json in (False, True):
        args = ["embed-db", "collections"]
        if is_json:
            args.extend(["--json"])
        result2 = runner.invoke(cli, args)
        assert result2.exit_code == 0
        if is_json:
            assert json.loads(result2.output) == [
                {"name": "items", "model": "embed-demo", "num_embeddings": 1}
            ]
        else:
            assert result2.output == "items: embed-demo\n  1 embedding\n"


@pytest.mark.parametrize(
    "args,expected_error",
    (
        ([], "Missing argument 'COLLECTION'"),
        (["badcollection", "-c", "content"], "Collection does not exist"),
        (["demo", "2"], "ID not found in collection"),
    ),
)
def test_similar_errors(args, expected_error, user_path_with_embeddings):
    runner = CliRunner()
    result = runner.invoke(cli, ["similar"] + args, catch_exceptions=False)
    assert result.exit_code != 0
    assert expected_error in result.output
