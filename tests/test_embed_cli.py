from click.testing import CliRunner
from llm.cli import cli
from llm import Collection
import json
import pytest
import sqlite_utils
from unittest.mock import ANY


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
@pytest.mark.parametrize("scenario", ("argument", "file", "stdin"))
def test_embed_output_format(tmpdir, format_, expected, scenario):
    runner = CliRunner()
    args = ["embed", "--format", format_, "-m", "embed-demo"]
    input = None
    if scenario == "argument":
        args.extend(["-c", "hello world"])
    elif scenario == "file":
        path = tmpdir / "input.txt"
        path.write_text("hello world", "utf-8")
        args.extend(["-i", str(path)])
    elif scenario == "stdin":
        input = "hello world"
        args.extend(["-i", "-"])
    result = runner.invoke(cli, args, input=input)
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


@pytest.mark.parametrize(
    "metadata,metadata_error",
    (
        (None, None),
        ('{"foo": "bar"}', None),
        ('{"foo": [1, 2, 3]}', None),
        ("[1, 2, 3]", "Metadata must be a JSON object"),  # Must be a dictionary
        ('{"foo": "incomplete}', "Metadata must be valid JSON"),
    ),
)
def test_embed_store(user_path, metadata, metadata_error):
    embeddings_db = user_path / "embeddings.db"
    assert not embeddings_db.exists()
    runner = CliRunner()
    result = runner.invoke(cli, ["embed", "-c", "hello", "-m", "embed-demo"])
    assert result.exit_code == 0
    # Should not have created the table
    assert not embeddings_db.exists()
    # Now run it to store
    args = ["embed", "-c", "hello", "-m", "embed-demo", "items", "1"]
    if metadata is not None:
        args.extend(("--metadata", metadata))
    result = runner.invoke(cli, args)
    if metadata_error:
        # Should have returned an error message about invalid metadata
        assert result.exit_code == 2
        assert metadata_error in result.output
        return
    # No error, should have succeeded and stored the data
    assert result.exit_code == 0
    assert embeddings_db.exists()
    # Check the contents
    db = sqlite_utils.Database(str(embeddings_db))
    assert list(db["collections"].rows) == [
        {"id": 1, "name": "items", "model": "embed-demo"}
    ]
    expected_metadata = None
    if metadata and not metadata_error:
        expected_metadata = metadata
    rows = list(db["embeddings"].rows)
    assert rows == [
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
            "content_hash": Collection.content_hash("hello"),
            "metadata": expected_metadata,
            "updated": ANY,
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

    # And test deleting it too
    result = runner.invoke(cli, ["embed-db", "delete-collection", "items"])
    assert result.exit_code == 0
    assert db["collections"].count == 0
    assert db["embeddings"].count == 0


def test_collection_delete_errors(user_path):
    db = sqlite_utils.Database(str(user_path / "embeddings.db"))
    collection = Collection("items", db, model_id="embed-demo")
    collection.embed("1", "hello")
    assert db["collections"].count == 1
    assert db["embeddings"].count == 1
    runner = CliRunner()
    result = runner.invoke(
        cli, ["embed-db", "delete-collection", "does-not-exist"], catch_exceptions=False
    )
    assert result.exit_code == 1
    assert "Collection does not exist" in result.output
    assert db["collections"].count == 1


@pytest.mark.parametrize(
    "args,expected_error",
    (
        ([], "Missing argument 'COLLECTION'"),
        (["badcollection", "-c", "content"], "Collection does not exist"),
        (["demo", "bad-id"], "ID not found in collection"),
    ),
)
def test_similar_errors(args, expected_error, user_path_with_embeddings):
    runner = CliRunner()
    result = runner.invoke(cli, ["similar"] + args, catch_exceptions=False)
    assert result.exit_code != 0
    assert expected_error in result.output


def test_similar_by_id_cli(user_path_with_embeddings):
    runner = CliRunner()
    result = runner.invoke(cli, ["similar", "demo", "1"], catch_exceptions=False)
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "id": "2",
        "score": pytest.approx(0.9863939238321437),
        "content": None,
        "metadata": None,
    }


@pytest.mark.parametrize("scenario", ("argument", "file", "stdin"))
def test_similar_by_content_cli(tmpdir, user_path_with_embeddings, scenario):
    runner = CliRunner()
    args = ["similar", "demo"]
    input = None
    if scenario == "argument":
        args.extend(["-c", "hello world"])
    elif scenario == "file":
        path = tmpdir / "content.txt"
        path.write_text("hello world", "utf-8")
        args.extend(["-i", str(path)])
    elif scenario == "stdin":
        input = "hello world"
        args.extend(["-i", "-"])
    result = runner.invoke(cli, args, input=input, catch_exceptions=False)
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "id": "1",
        "score": pytest.approx(0.9999999999999999),
        "content": None,
        "metadata": None,
    }
    assert json.loads(lines[1]) == {
        "id": "2",
        "score": pytest.approx(0.9863939238321437),
        "content": None,
        "metadata": None,
    }


@pytest.mark.parametrize("use_stdin", (False, True))
@pytest.mark.parametrize("prefix", (None, "prefix"))
@pytest.mark.parametrize(
    "filename,content",
    (
        ("phrases.csv", "id,phrase\n1,hello world\n2,goodbye world"),
        ("phrases.tsv", "id\tphrase\n1\thello world\n2\tgoodbye world"),
        (
            "phrases.jsonl",
            '{"id": 1, "phrase": "hello world"}\n{"id": 2, "phrase": "goodbye world"}',
        ),
        (
            "phrases.json",
            '[{"id": 1, "phrase": "hello world"}, {"id": 2, "phrase": "goodbye world"}]',
        ),
    ),
)
def test_embed_multi_file_input(tmpdir, use_stdin, prefix, filename, content):
    db_path = tmpdir / "embeddings.db"
    args = ["embed-multi", "phrases", "-d", str(db_path), "-m", "embed-demo"]
    input = None
    if use_stdin:
        input = content
        args.append("-")
    else:
        path = tmpdir / filename
        path.write_text(content, "utf-8")
        args.append(str(path))
    if prefix:
        args.extend(("--prefix", prefix))
    # Auto-detection can't detect JSON-nl, so make that explicit
    if filename.endswith(".jsonl"):
        args.extend(("--format", "nl"))
    runner = CliRunner()
    result = runner.invoke(cli, args, input=input)
    assert result.exit_code == 0
    # Check that everything was embedded correctly
    db = sqlite_utils.Database(str(db_path))
    assert db["embeddings"].count == 2
    ids = [row["id"] for row in db["embeddings"].rows]
    expected_ids = ["1", "2"]
    if prefix:
        expected_ids = ["prefix1", "prefix2"]
    assert ids == expected_ids


@pytest.mark.parametrize("use_other_db", (True, False))
@pytest.mark.parametrize("prefix", (None, "prefix"))
def test_sql(tmpdir, use_other_db, prefix):
    db_path = str(tmpdir / "embeddings.db")
    db = sqlite_utils.Database(db_path)
    extra_args = []
    if use_other_db:
        db_path2 = str(tmpdir / "other.db")
        db = sqlite_utils.Database(db_path2)
        extra_args = ["--attach", "other", db_path2]

    if prefix:
        extra_args.extend(("--prefix", prefix))

    db["content"].insert_all(
        [
            {"id": 1, "name": "cli", "description": "Command line interface"},
            {"id": 2, "name": "sql", "description": "Structured query language"},
        ],
        pk="id",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "embed-multi",
            "stuff",
            "-d",
            db_path,
            "--sql",
            "select * from content",
            "-m",
            "embed-demo",
            "--store",
        ]
        + extra_args,
    )
    assert result.exit_code == 0
    embeddings_db = sqlite_utils.Database(db_path)
    assert embeddings_db["embeddings"].count == 2
    rows = list(embeddings_db.query("select id, content from embeddings"))
    assert rows == [
        {"id": (prefix or "") + "1", "content": "cli Command line interface"},
        {"id": (prefix or "") + "2", "content": "sql Structured query language"},
    ]


def test_default_embedding_model():
    runner = CliRunner()
    result = runner.invoke(cli, ["embed-models", "default"])
    assert result.exit_code == 0
    assert result.output == "<No default embedding model set>\n"
    result2 = runner.invoke(cli, ["embed-models", "default", "ada-002"])
    assert result2.exit_code == 0
    result3 = runner.invoke(cli, ["embed-models", "default"])
    assert result3.exit_code == 0
    assert result3.output == "ada-002\n"
    result4 = runner.invoke(cli, ["embed-models", "default", "--remove-default"])
    assert result4.exit_code == 0
    result5 = runner.invoke(cli, ["embed-models", "default"])
    assert result5.exit_code == 0
    assert result5.output == "<No default embedding model set>\n"
