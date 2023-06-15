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


def test_uses_correct_key(requests_mock, monkeypatch, tmpdir):
    keys_path = tmpdir / "keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "openai": "from-keys-file",
                "other": "other-key",
            }
        ),
        "utf-8",
    )
    monkeypatch.setenv("LLM_KEYS_PATH", str(keys_path))
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    mocked = requests_mock.post(
        "https://api.openai.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "Bob, Alice, Eve"}}]},
        headers={"Content-Type": "application/json"},
    )

    def assert_key(key):
        assert mocked.last_request.headers["Authorization"] == "Bearer {}".format(key)

    runner = CliRunner()
    # Called without --key uses environment variable
    result = runner.invoke(cli, ["hello", "--no-stream"], catch_exceptions=False)
    assert result.exit_code == 0
    assert_key("from-env")
    # Called without --key and with no environment variable uses keys.json
    monkeypatch.setenv("OPENAI_API_KEY", "")
    result2 = runner.invoke(cli, ["hello", "--no-stream"], catch_exceptions=False)
    assert result2.exit_code == 0
    assert_key("from-keys-file")
    # Called with --key name-in-keys.json uses that value
    result3 = runner.invoke(
        cli, ["hello", "--key", "other", "--no-stream"], catch_exceptions=False
    )
    assert result3.exit_code == 0
    assert_key("other-key")
    # Called with --key something-else uses exactly that
    result4 = runner.invoke(
        cli, ["hello", "--key", "custom-key", "--no-stream"], catch_exceptions=False
    )
    assert result4.exit_code == 0
    assert_key("custom-key")
