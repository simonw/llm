from click.testing import CliRunner
from platformdirs import user_data_dir
import json
from llm.cli import cli
import os
import pytest


@pytest.mark.parametrize("env", ({}, {"LLM_KEYS_PATH": "/tmp/foo.json"}))
def test_keys_path(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "path"])
    assert result.exit_code == 0
    if env:
        expected = env["LLM_KEYS_PATH"]
    else:
        expected = os.path.join(
            user_data_dir("io.datasette.llm", "Datasette"), "keys.json"
        )
    assert result.output.strip() == expected


def test_keys_set(monkeypatch, tmpdir):
    keys_path = str(tmpdir / "keys.json")
    monkeypatch.setenv("LLM_KEYS_PATH", keys_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "set", "openai"], input="foo")
    assert result.exit_code == 0
    content = open(keys_path).read()
    assert json.loads(content) == {
        "// Note": "This file stores secret API credentials. Do not share!",
        "openai": "foo",
    }
