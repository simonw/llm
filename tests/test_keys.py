from click.testing import CliRunner
import json
from llm.cli import cli
import pathlib
import pytest


@pytest.mark.parametrize("env", ({}, {"LLM_USER_PATH": "/tmp/llm-keys-test"}))
def test_keys_in_user_path(monkeypatch, env, user_path):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "path"])
    assert result.exit_code == 0
    if env:
        expected = env["LLM_USER_PATH"] + "/keys.json"
    else:
        expected = user_path + "/keys.json"
    assert result.output.strip() == expected


def test_keys_set(monkeypatch, tmpdir):
    user_path = str(tmpdir / "user/keys")
    monkeypatch.setenv("LLM_USER_PATH", user_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "set", "openai"], input="foo")
    assert result.exit_code == 0
    content = open(user_path + "/keys.json").read()
    assert json.loads(content) == {
        "// Note": "This file stores secret API credentials. Do not share!",
        "openai": "foo",
    }


@pytest.mark.parametrize("args", (["keys", "list"], ["keys"]))
def test_keys_list(monkeypatch, tmpdir, args):
    user_path = str(tmpdir / "user/keys")
    monkeypatch.setenv("LLM_USER_PATH", user_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "set", "openai"], input="foo")
    assert result.exit_code == 0
    result2 = runner.invoke(cli, args)
    assert result2.exit_code == 0
    assert result2.output.strip() == "openai"
