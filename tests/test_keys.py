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


def test_uses_correct_key(mocked_openai, monkeypatch, tmpdir):
    user_dir = tmpdir / "user-dir"
    pathlib.Path(user_dir).mkdir()
    keys_path = user_dir / "keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "openai": "from-keys-file",
                "other": "other-key",
            }
        ),
        "utf-8",
    )
    monkeypatch.setenv("LLM_USER_PATH", str(user_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")

    def assert_key(key):
        assert mocked_openai.last_request.headers[
            "Authorization"
        ] == "Bearer {}".format(key)

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
