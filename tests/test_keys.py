from click.testing import CliRunner
import json
from llm.cli import cli
import pathlib
import pytest
import sys


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
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


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_keys_set(monkeypatch, tmpdir):
    user_path = tmpdir / "user/keys"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    keys_path = user_path / "keys.json"
    assert not keys_path.exists()
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "set", "openai"], input="foo")
    assert result.exit_code == 0
    assert keys_path.exists()
    # Should be chmod 600
    assert oct(keys_path.stat().mode)[-3:] == "600"
    content = keys_path.read_text("utf-8")
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


@pytest.mark.httpx_mock(
    assert_all_requests_were_expected=False, can_send_already_matched_responses=True
)
def test_uses_correct_key(mocked_openai_chat, monkeypatch, tmpdir):
    user_dir = tmpdir / "user-dir"
    pathlib.Path(user_dir).mkdir()
    keys_path = user_dir / "keys.json"
    KEYS = {
        "openai": "from-keys-file",
        "other": "other-key",
    }
    keys_path.write_text(json.dumps(KEYS), "utf-8")
    monkeypatch.setenv("LLM_USER_PATH", str(user_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")

    def assert_key(key):
        request = mocked_openai_chat.get_requests()[-1]
        assert request.headers["Authorization"] == "Bearer {}".format(key)

    runner = CliRunner()

    # Called without --key uses stored key
    result = runner.invoke(cli, ["hello", "--no-stream"], catch_exceptions=False)
    assert result.exit_code == 0
    assert_key("from-keys-file")

    # Called without --key and without keys.json uses environment variable
    keys_path.write_text("{}", "utf-8")
    result2 = runner.invoke(cli, ["hello", "--no-stream"], catch_exceptions=False)
    assert result2.exit_code == 0
    assert_key("from-env")
    keys_path.write_text(json.dumps(KEYS), "utf-8")

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
