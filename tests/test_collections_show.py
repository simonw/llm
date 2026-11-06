import base64
import csv
import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli


@pytest.mark.parametrize("format_", ("json", "nl", "csv", "tsv"))
@pytest.mark.parametrize("database_option", ("default", "argument", "environment"))
def test_collections_show(db_factory, user_path, monkeypatch, format_, database_option):
    path = user_path / (
        "embeddings.db" if database_option == "default" else "custom # embeddings.db"
    )
    db = db_factory(str(path))
    collection = llm.Collection("notes", db, model_id="embed-demo")
    collection.embed(
        "text", 'Café, "quoted"\nsecond line', store=True, metadata={"x": [1]}
    )
    collection.embed("unstored", "not stored")
    # Include binary data without requiring a binary embedding plugin.
    db["embeddings"].insert(
        {
            "collection_id": collection.id,
            "id": "binary",
            "embedding": llm.encode([1.0, 2.0]),
            "content_blob": b"\x00\xff",
            "metadata": None,
            "updated": 123,
        }
    )
    llm.Collection("other", db, model_id="embed-demo").embed("other", "unrelated")
    # Export must not need the original model to be installed.
    db["collections"].update(collection.id, {"model": "uninstalled-model"})
    before = Path(str(path)).read_bytes()
    args = ["collections", "show", "notes", "--format", format_]
    if database_option == "argument":
        args.extend(["--database", str(path)])
    elif database_option == "environment":
        monkeypatch.setenv("LLM_EMBEDDINGS_DB", str(path))
    result = CliRunner().invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert Path(str(path)).read_bytes() == before
    if format_ == "json":
        rows = json.loads(result.output)
    elif format_ == "nl":
        rows = [json.loads(line) for line in result.output.splitlines()]
    else:
        rows = list(
            csv.DictReader(
                io.StringIO(result.output), delimiter="," if format_ == "csv" else "\t"
            )
        )
        for row in rows:
            row["embedding"] = json.loads(row["embedding"])
            row["metadata"] = json.loads(row["metadata"]) if row["metadata"] else None
            row["content"] = row["content"] or None
            row["content_blob"] = row["content_blob"] or None
    assert [row["id"] for row in rows] == ["binary", "text", "unstored"]
    assert rows[0]["embedding"] == [1.0, 2.0]
    assert base64.b64decode(rows[0]["content_blob"]) == b"\x00\xff"
    assert rows[1]["content"] == 'Café, "quoted"\nsecond line'
    assert rows[1]["metadata"] == {"x": [1]}
    assert rows[2]["content"] is None
    assert rows[2]["metadata"] is None


@pytest.mark.parametrize("format_", ("json", "nl", "csv", "tsv"))
def test_collections_show_empty(db_factory, user_path, format_):
    db = db_factory(str(user_path / "embeddings.db"))
    llm.Collection("empty", db, model_id="embed-demo")
    result = CliRunner().invoke(
        cli, ["collections", "show", "empty", "--format", format_]
    )
    assert result.exit_code == 0, result.output
    if format_ == "json":
        assert json.loads(result.output) == []
    elif format_ == "nl":
        assert result.output == ""
    else:
        assert result.output.splitlines() == [
            ("," if format_ == "csv" else "\t").join(
                ["id", "embedding", "content", "content_blob", "metadata", "updated"]
            )
        ]


def test_collections_show_missing_database(user_path):
    result = CliRunner().invoke(cli, ["collections", "show", "missing"])
    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert not (user_path / "embeddings.db").exists()


def test_collections_show_missing_collection(db_factory, user_path):
    db = db_factory(str(user_path / "embeddings.db"))
    llm.Collection("existing", db, model_id="embed-demo")
    result = CliRunner().invoke(cli, ["collections", "show", "missing"])
    assert result.exit_code == 1
    assert "Collection 'missing' does not exist" in result.output
    assert db["collections"].count == 1


def test_collections_show_default_format(db_factory, user_path):
    db = db_factory(str(user_path / "embeddings.db"))
    collection = llm.Collection("notes", db, model_id="embed-demo")
    collection.embed("1", "hello", store=True)
    result = CliRunner().invoke(cli, ["collections", "show", "notes"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["content"] == "hello"


def test_collections_show_invalid_database(user_path):
    path = user_path / "embeddings.db"
    path.write_text("not a database", "utf-8")
    result = CliRunner().invoke(cli, ["collections", "show", "notes"])
    assert result.exit_code == 1
    assert "file is not a database" in result.output
