import json
import os
import textwrap
from importlib.metadata import version
from unittest import mock

import pytest
import yaml
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.migrations import migrate


def test_fragments_set_show_remove(user_path, tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with open("fragment1.txt", "w") as f:
        f.write("Hello fragment 1")

    # llm fragments --aliases should return nothing
    assert runner.invoke(cli, ["fragments", "list", "--aliases"]).output == ""
    assert (
        runner.invoke(cli, ["fragments", "set", "f1", "fragment1.txt"]).exit_code == 0
    )
    result1 = runner.invoke(cli, ["fragments", "show", "f1"])
    assert result1.exit_code == 0
    assert result1.output == "Hello fragment 1\n"

    # Should be in the list now
    def get_list():
        result2 = runner.invoke(cli, ["fragments", "list"])
        assert result2.exit_code == 0
        return yaml.safe_load(result2.output)

    # And in llm fragments --aliases
    assert "f1" in runner.invoke(cli, ["fragments", "list", "--aliases"]).output

    loaded1 = get_list()
    assert set(loaded1[0].keys()) == {
        "aliases",
        "content",
        "datetime_utc",
        "source",
        "hash",
    }
    assert loaded1[0]["content"] == "Hello fragment 1"
    assert loaded1[0]["aliases"] == ["f1"]

    # Show should work against both alias and hash
    for key in ("f1", loaded1[0]["hash"]):
        result3 = runner.invoke(cli, ["fragments", "show", key])
        assert result3.exit_code == 0
        assert result3.output == "Hello fragment 1\n"

    # But not for an invalid alias
    result4 = runner.invoke(cli, ["fragments", "show", "badalias"])
    assert result4.exit_code == 1
    assert "Fragment 'badalias' not found" in result4.output

    # Remove that alias
    result5 = runner.invoke(cli, ["fragments", "remove", "f1"])
    assert result5.exit_code == 0
    # Should still be in list but no alias
    loaded2 = get_list()
    assert loaded2[0]["aliases"] == []
    assert loaded2[0]["content"] == "Hello fragment 1"

    # And --aliases list should be empty
    assert runner.invoke(cli, ["fragments", "list", "--aliases"]).output == ""


def test_fragments_list(db_factory, user_path):
    runner = CliRunner()
    db = db_factory(str(user_path / "logs.db"))
    with db.conn:
        migrate(db)
        db["fragments"].insert_all(
            [
                {
                    "id": 1,
                    "content": "1",
                    "datetime_utc": "2023-10-01T00:00:00Z",
                    "source": "file1.txt",
                    "hash": "hash1",
                },
                {
                    "id": 2,
                    "content": "2",
                    "datetime_utc": "2022-10-01T00:00:00Z",
                    "source": "file2.txt",
                    "hash": "hash2",
                },
                {
                    "id": 3,
                    "content": "3",
                    "datetime_utc": "2024-10-01T00:00:00Z",
                    "source": "file3.txt",
                    "hash": "hash3",
                },
            ]
        )
        db["fragment_aliases"].insert(
            {
                "alias": "f1",
                "fragment_id": 1,
            }
        )
    result = runner.invoke(cli, ["fragments", "list"])
    assert result.exit_code == 0
    assert result.output.strip() == (textwrap.dedent("""
            - hash: hash2
              aliases: []
              datetime_utc: '2022-10-01T00:00:00Z'
              source: file2.txt
              content: '2'
            - hash: hash1
              aliases:
              - f1
              datetime_utc: '2023-10-01T00:00:00Z'
              source: file1.txt
              content: '1'
            - hash: hash3
              aliases: []
              datetime_utc: '2024-10-01T00:00:00Z'
              source: file3.txt
              content: '3'
            """).strip())


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize(
    "queries, expected",
    [
        (["primary"], [("hash1", {"primary", "secondary"})]),
        (["secondary"], [("hash1", {"primary", "secondary"})]),
        (["primary", "secondary"], [("hash1", {"primary", "secondary"})]),
        (["secondary", "primary"], [("hash1", {"primary", "secondary"})]),
        (["primary", "Shared"], [("hash1", {"primary", "secondary"})]),
        (["primary", "unrelated"], []),
        (["missing"], []),
        (["shared.txt"], [("hash1", {"primary", "secondary"})]),
        (["hash1"], [("hash1", {"primary", "secondary"})]),
        (["Unaliased"], [("hash3", set())]),
    ],
)
def test_fragments_list_queries_keep_all_aliases(
    db_factory, user_path, queries, expected, json_output
):
    db = db_factory(str(user_path / "logs.db"))
    migrate(db)
    with db.atomic():
        db["fragments"].insert_all(
            [
                {
                    "id": 1,
                    "content": "Shared document",
                    "datetime_utc": "2023-10-01T00:00:00Z",
                    "source": "shared.txt",
                    "hash": "hash1",
                },
                {
                    "id": 2,
                    "content": "Different document",
                    "datetime_utc": "2023-10-02T00:00:00Z",
                    "source": "different.txt",
                    "hash": "hash2",
                },
                {
                    "id": 3,
                    "content": "Unaliased document",
                    "datetime_utc": "2023-10-03T00:00:00Z",
                    "source": "unaliased.txt",
                    "hash": "hash3",
                },
            ]
        )
        db["fragment_aliases"].insert_all(
            [
                {"alias": "primary", "fragment_id": 1},
                {"alias": "secondary", "fragment_id": 1},
                {"alias": "unrelated", "fragment_id": 2},
            ]
        )
    args = ["fragments", "list"]
    for query in queries:
        args.extend(["-q", query])
    if json_output:
        args.append("--json")
    result = CliRunner().invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output) if json_output else yaml.safe_load(result.output)
    assert [(row["hash"], set(row["aliases"])) for row in (rows or [])] == expected


def test_fragment_absolute_path(user_path, tmp_path):
    path = tmp_path / "fragment.txt"
    path.write_text("Hello from an absolute path")

    result = CliRunner().invoke(
        cli, ["prompt", "-m", "echo", "-f", str(path)], catch_exceptions=False
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "prompt": "Hello from an absolute path",
        "system": "",
        "attachments": [],
        "stream": True,
        "previous": [],
    }


@pytest.mark.parametrize(
    "argument,expected_prompt,expected_sources",
    (
        ("demo:hello world", "hello world\ngoodbye world", ["demo:1", "demo:2"]),
        ("demo:hello world:1", "hello world", ["demo:1"]),
        ("demo:goodbye world:1", "goodbye world", ["demo:2"]),
    ),
)
def test_similar_fragment_loader(
    user_path_with_embeddings, logs_db, argument, expected_prompt, expected_sources
):
    result = CliRunner().invoke(
        cli,
        ["prompt", "-m", "echo", "-f", f"similar:{argument}"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["prompt"] == expected_prompt
    # Each result is logged as a separate fragment
    sources = [row["source"] for row in logs_db.query("select source from fragments")]
    assert sorted(sources) == expected_sources


def test_similar_fragment_loader_embeddings_db_env(
    user_path, tmp_path, db_factory, monkeypatch
):
    path = tmp_path / "other.db"
    collection = llm.Collection("other", db_factory(str(path)), model_id="embed-demo")
    collection.embed("1", "hello world", store=True)
    monkeypatch.setenv("LLM_EMBEDDINGS_DB", str(path))
    result = CliRunner().invoke(
        cli,
        ["prompt", "-m", "echo", "-f", "similar:other:hello"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["prompt"] == "hello world"


@pytest.mark.parametrize(
    "argument,expected_error",
    (
        ("demo", "Argument must be in the form collection:search term"),
        ("demo:", "Argument must be in the form collection:search term"),
        (":hello", "Argument must be in the form collection:search term"),
        ("demo:hello:0", "Number of results must be at least 1"),
        ("missing:hello", "Collection 'missing' does not exist"),
        ("unstored:hello", "No stored text content found for 'hello'"),
        ("binary:hello", "No stored text content found for 'hello'"),
    ),
)
def test_similar_fragment_loader_errors(
    user_path_with_embeddings, user_path, db_factory, argument, expected_error
):
    db = db_factory(str(user_path / "embeddings.db"))
    llm.Collection("unstored", db, model_id="embed-demo").embed("1", "hello world")
    # Binary content is stored in content_blob, which is not returned
    llm.Collection("binary", db, model_id="embed-demo").embed(
        "1", b"hello world", store=True
    )
    result = CliRunner().invoke(
        cli, ["prompt", "-m", "echo", "-f", f"similar:{argument}"]
    )
    assert result.exit_code == 1
    assert f"Could not load fragment similar:{argument}: {expected_error}" in (
        result.output
    )


def test_similar_fragment_loader_no_embeddings_db(user_path):
    result = CliRunner().invoke(
        cli, ["prompt", "-m", "echo", "-f", "similar:demo:hello"]
    )
    assert result.exit_code == 1
    assert "Embeddings database" in result.output
    assert "does not exist" in result.output
    # The loader should not create an empty database
    assert not (user_path / "embeddings.db").exists()


def test_similar_fragment_loader_unrelated_db(
    user_path, tmp_path, db_factory, monkeypatch
):
    path = tmp_path / "other.db"
    db = db_factory(str(path))
    db["dogs"].insert({"name": "Cleo"})
    monkeypatch.setenv("LLM_EMBEDDINGS_DB", str(path))
    result = CliRunner().invoke(
        cli, ["prompt", "-m", "echo", "-f", "similar:demo:hello"]
    )
    assert result.exit_code == 1
    assert f"No embeddings table found in {path}" in result.output
    # The loader should not add the embeddings tables to other databases
    assert db.table_names() == ["dogs"]


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
def test_fragment_url_user_agent(mocked_openai_chat, user_path):
    mocked_openai_chat.add_response(
        url="https://example.com/fragment.txt",
        text="Hello from URL",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "prompt",
            "-m",
            "gpt-4o-mini",
            "-f",
            "https://example.com/fragment.txt",
        ],
    )
    assert result.exit_code == 0

    # Verify the User-Agent header was sent for the fragment URL request
    requests = mocked_openai_chat.get_requests()
    fragment_request = next(r for r in requests if "example.com" in str(r.url))
    llm_version = version("llm")
    expected_user_agent = f"llm/{llm_version} (https://llm.datasette.io/)"
    assert fragment_request.headers["User-Agent"] == expected_user_agent
