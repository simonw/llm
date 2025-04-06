from click.testing import CliRunner
from llm.cli import cli
import llm
import json
import pytest
import re


@pytest.mark.parametrize("model_id_or_alias", ("gpt-3.5-turbo", "chatgpt"))
def test_set_alias(model_id_or_alias):
    with pytest.raises(llm.UnknownModelError):
        llm.get_model("this-is-a-new-alias")
    llm.set_alias("this-is-a-new-alias", model_id_or_alias)
    assert llm.get_model("this-is-a-new-alias").model_id == "gpt-3.5-turbo"


def test_remove_alias():
    with pytest.raises(KeyError):
        llm.remove_alias("some-other-alias")
    llm.set_alias("some-other-alias", "gpt-3.5-turbo")
    assert llm.get_model("some-other-alias").model_id == "gpt-3.5-turbo"
    llm.remove_alias("some-other-alias")
    with pytest.raises(llm.UnknownModelError):
        llm.get_model("some-other-alias")


@pytest.mark.parametrize("args", (["aliases", "list"], ["aliases"]))
def test_cli_aliases_list(args):
    llm.set_alias("e-demo", "embed-demo")
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    for line in (
        "3.5         : gpt-3.5-turbo\n"
        "chatgpt     : gpt-3.5-turbo\n"
        "chatgpt-16k : gpt-3.5-turbo-16k\n"
        "3.5-16k     : gpt-3.5-turbo-16k\n"
        "4           : gpt-4\n"
        "gpt4        : gpt-4\n"
        "4-32k       : gpt-4-32k\n"
        "e-demo      : embed-demo (embedding)\n"
        "ada         : text-embedding-ada-002 (embedding)\n"
    ).split("\n"):
        line = line.strip()
        if not line:
            continue
        # Turn the whitespace into a regex
        regex = r"\s+".join(re.escape(part) for part in line.split())
        assert re.search(regex, result.output)


@pytest.mark.parametrize("args", (["aliases", "list"], ["aliases"]))
def test_cli_aliases_list_json(args):
    llm.set_alias("e-demo", "embed-demo")
    runner = CliRunner()
    result = runner.invoke(cli, args + ["--json"])
    assert result.exit_code == 0
    assert (
        json.loads(result.output).items()
        >= {
            "3.5": "gpt-3.5-turbo",
            "chatgpt": "gpt-3.5-turbo",
            "chatgpt-16k": "gpt-3.5-turbo-16k",
            "3.5-16k": "gpt-3.5-turbo-16k",
            "4": "gpt-4",
            "gpt4": "gpt-4",
            "4-32k": "gpt-4-32k",
            "ada": "text-embedding-ada-002",
            "e-demo": "embed-demo",
        }.items()
    )


@pytest.mark.parametrize(
    "args,expected,expected_error",
    (
        (["foo", "bar"], {"foo": "bar"}, None),
        (["foo", "-q", "mo"], {"foo": "mock"}, None),
        (["foo", "-q", "mog"], None, "No model found matching query: mog"),
    ),
)
def test_cli_aliases_set(user_path, args, expected, expected_error):
    # Should be not aliases.json at start
    assert not (user_path / "aliases.json").exists()
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "set"] + args)
    if not expected_error:
        assert result.exit_code == 0
        assert (user_path / "aliases.json").exists()
        assert json.loads((user_path / "aliases.json").read_text("utf-8")) == expected
    else:
        assert result.exit_code == 1
        assert result.output.strip() == f"Error: {expected_error}"


def test_cli_aliases_path(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "path"])
    assert result.exit_code == 0
    assert result.output.strip() == str(user_path / "aliases.json")


def test_cli_aliases_remove(user_path):
    (user_path / "aliases.json").write_text(json.dumps({"foo": "bar"}), "utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "remove", "foo"])
    assert result.exit_code == 0
    assert json.loads((user_path / "aliases.json").read_text("utf-8")) == {}


def test_cli_aliases_remove_invalid(user_path):
    (user_path / "aliases.json").write_text(json.dumps({"foo": "bar"}), "utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "remove", "invalid"])
    assert result.exit_code == 1
    assert result.output == "Error: No such alias: invalid\n"


@pytest.mark.parametrize("args", (["models"], ["models", "list"]))
def test_cli_aliases_are_registered(user_path, args):
    (user_path / "aliases.json").write_text(
        json.dumps({"foo": "bar", "turbo": "gpt-3.5-turbo"}), "utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    assert "gpt-3.5-turbo (aliases: 3.5, chatgpt, turbo)" in result.output
