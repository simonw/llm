from click.testing import CliRunner
from llm.cli import cli
import json
import pytest


@pytest.mark.parametrize("args", (["aliases", "list"], ["aliases"]))
def test_aliases_list(args):
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    assert result.output == (
        "3.5         : gpt-3.5-turbo\n"
        "chatgpt     : gpt-3.5-turbo\n"
        "chatgpt-16k : gpt-3.5-turbo-16k\n"
        "3.5-16k     : gpt-3.5-turbo-16k\n"
        "4           : gpt-4\n"
        "gpt4        : gpt-4\n"
        "4-32k       : gpt-4-32k\n"
    )


@pytest.mark.parametrize("args", (["aliases", "list"], ["aliases"]))
def test_aliases_list_json(args):
    runner = CliRunner()
    result = runner.invoke(cli, args + ["--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "3.5": "gpt-3.5-turbo",
        "chatgpt": "gpt-3.5-turbo",
        "chatgpt-16k": "gpt-3.5-turbo-16k",
        "3.5-16k": "gpt-3.5-turbo-16k",
        "4": "gpt-4",
        "gpt4": "gpt-4",
        "4-32k": "gpt-4-32k",
    }


def test_aliases_set(user_path):
    # Should be not aliases.json at start
    assert not (user_path / "aliases.json").exists()
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "set", "foo", "bar"])
    assert result.exit_code == 0
    assert (user_path / "aliases.json").exists()
    assert json.loads((user_path / "aliases.json").read_text("utf-8")) == {"foo": "bar"}


def test_aliases_path(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "path"])
    assert result.exit_code == 0
    assert result.output.strip() == str(user_path / "aliases.json")


def test_aliases_remove(user_path):
    (user_path / "aliases.json").write_text(json.dumps({"foo": "bar"}), "utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "remove", "foo"])
    assert result.exit_code == 0
    assert json.loads((user_path / "aliases.json").read_text("utf-8")) == {}


def test_aliases_remove_invalid(user_path):
    (user_path / "aliases.json").write_text(json.dumps({"foo": "bar"}), "utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "remove", "invalid"])
    assert result.exit_code == 1
    assert result.output == "Error: Alias not found: invalid\n"


@pytest.mark.parametrize("args", (["models"], ["models", "list"]))
def test_aliases_are_registered(user_path, args):
    (user_path / "aliases.json").write_text(
        json.dumps({"foo": "bar", "turbo": "gpt-3.5-turbo"}), "utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    assert "gpt-3.5-turbo (aliases: 3.5, chatgpt, turbo)" in result.output
