import json
import os
import textwrap
from importlib.metadata import version
from unittest import mock

import sqlite_utils
import yaml
from click.testing import CliRunner

from llm.cli import cli
from llm.migrations import migrate


def test_fragments_set_show_remove(user_path):
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("fragment1.txt", "w") as f:
            f.write("Hello fragment 1")

        # llm fragments --aliases should return nothing
        assert runner.invoke(cli, ["fragments", "list", "--aliases"]).output == ""
        assert (
            runner.invoke(cli, ["fragments", "set", "f1", "fragment1.txt"]).exit_code
            == 0
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


def test_fragments_list(user_path):
    runner = CliRunner()
    db = sqlite_utils.Database(str(user_path / "logs.db"))
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


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
def test_fragment_url_user_agent(mocked_openai_chat, httpx_mock, user_path):
    httpx_mock.add_response(
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
    requests = httpx_mock.get_requests()
    fragment_request = next(r for r in requests if "example.com" in str(r.url))
    llm_version = version("llm")
    expected_user_agent = f"llm/{llm_version} (https://llm.datasette.io/)"
    assert fragment_request.headers["User-Agent"] == expected_user_agent
