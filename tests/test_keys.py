import json
import pathlib
import sys

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli


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


@pytest.mark.parametrize(
    "value", ("sk-bad\u221akey", "sk-zero\u200bwidth", "caf\u00e9")
)
def test_keys_set_rejects_non_ascii(monkeypatch, tmpdir, value):
    # https://github.com/simonw/llm/issues/576
    user_path = tmpdir / "user/keys"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    keys_path = user_path / "keys.json"
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "set", "openai", "--value", value])
    assert result.exit_code == 1
    assert "API keys must contain only ASCII characters" in result.output
    assert "U+" in result.output
    # Nothing should have been written
    assert not keys_path.exists()


NON_ASCII_KEY = "sk-bad\u221akey"


@pytest.fixture
def keys_dir(monkeypatch, tmpdir):
    path = tmpdir / "user-dir"
    pathlib.Path(path).mkdir()
    monkeypatch.setenv("LLM_USER_PATH", str(path))
    monkeypatch.delenv("LLM_TEST_KEY", raising=False)
    return path


def test_get_key_rejects_non_ascii_stored_key(keys_dir):
    # A key saved before keys set started rejecting these still needs a clear error
    (keys_dir / "keys.json").write_text(json.dumps({"openai": NON_ASCII_KEY}), "utf-8")
    with pytest.raises(ValueError) as exc_info:
        llm.get_key(alias="openai")
    message = str(exc_info.value)
    assert "API keys must contain only ASCII characters" in message
    assert "U+221A" in message
    assert "stored key 'openai'" in message
    # Same via an alias given as the explicit key, and via the key itself
    with pytest.raises(ValueError) as alias_exc_info:
        llm.get_key(input="openai")
    assert "U+221A" in str(alias_exc_info.value)
    # The key itself is never included in the message
    assert NON_ASCII_KEY not in message
    assert "sk-bad" not in message


def test_get_key_rejects_non_ascii_explicit_key(keys_dir):
    with pytest.raises(ValueError) as exc_info:
        llm.get_key(input="sk-zero\u200bwidth")
    assert "U+200B" in str(exc_info.value)
    assert "sk-zero" not in str(exc_info.value)


def test_get_key_rejects_non_ascii_env_key(keys_dir, monkeypatch):
    monkeypatch.setenv("LLM_TEST_KEY", "caf\u00e9")
    with pytest.raises(ValueError) as exc_info:
        llm.get_key(alias="missing", env="LLM_TEST_KEY")
    message = str(exc_info.value)
    assert "U+00E9" in message
    assert "environment variable LLM_TEST_KEY" in message


def test_get_key_accepts_ascii_and_missing_keys(keys_dir, monkeypatch):
    (keys_dir / "keys.json").write_text(json.dumps({"openai": "sk-ok"}), "utf-8")
    monkeypatch.setenv("LLM_TEST_KEY", "from-env")
    assert llm.get_key(alias="openai") == "sk-ok"
    assert llm.get_key(input="openai") == "sk-ok"
    assert llm.get_key(input="custom-key") == "custom-key"
    assert llm.get_key(alias="missing", env="LLM_TEST_KEY") == "from-env"
    assert llm.get_key(alias="missing") is None


@pytest.mark.parametrize("source", ("stored", "env", "key"))
def test_prompt_with_non_ascii_key_shows_clear_error(keys_dir, monkeypatch, source):
    args = ["hello", "--no-stream", "-m", "gpt-4o-mini"]
    if source == "stored":
        (keys_dir / "keys.json").write_text(
            json.dumps({"openai": NON_ASCII_KEY}), "utf-8"
        )
    elif source == "env":
        monkeypatch.setenv("OPENAI_API_KEY", NON_ASCII_KEY)
    else:
        args += ["--key", NON_ASCII_KEY]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1
    assert "API keys must contain only ASCII characters" in result.output
    assert "U+221A" in result.output
    assert "ascii' codec" not in result.output
    assert NON_ASCII_KEY not in result.output


@pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
def test_keys_get(monkeypatch, tmpdir):
    user_path = tmpdir / "user/keys"
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))
    runner = CliRunner()
    result = runner.invoke(cli, ["keys", "set", "openai"], input="fx")
    assert result.exit_code == 0
    result2 = runner.invoke(cli, ["keys", "get", "openai"])
    assert result2.exit_code == 0
    assert result2.output.strip() == "fx"


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


@pytest.mark.httpx2_mock(
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
        assert request.headers["Authorization"] == f"Bearer {key}"

    runner = CliRunner()

    # Called without --key uses stored key
    result = runner.invoke(
        cli,
        ["hello", "--no-stream", "-m", "gpt-4o-mini"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert_key("from-keys-file")

    # Called without --key and without keys.json uses environment variable
    keys_path.write_text("{}", "utf-8")
    result2 = runner.invoke(
        cli,
        ["hello", "--no-stream", "-m", "gpt-4o-mini"],
        catch_exceptions=False,
    )
    assert result2.exit_code == 0
    assert_key("from-env")
    keys_path.write_text(json.dumps(KEYS), "utf-8")

    # Called with --key name-in-keys.json uses that value
    result3 = runner.invoke(
        cli,
        ["hello", "--key", "other", "--no-stream", "-m", "gpt-4o-mini"],
        catch_exceptions=False,
    )
    assert result3.exit_code == 0
    assert_key("other-key")

    # Called with --key something-else uses exactly that
    result4 = runner.invoke(
        cli,
        ["hello", "--key", "custom-key", "--no-stream", "-m", "gpt-4o-mini"],
        catch_exceptions=False,
    )
    assert result4.exit_code == 0
    assert_key("custom-key")
