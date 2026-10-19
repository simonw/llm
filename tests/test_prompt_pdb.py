import subprocess
import sys
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from llm.cli import cli


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("async_", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("error_type", [ValueError, NotImplementedError, RuntimeError])
def test_prompt_pdb_original_traceback(
    monkeypatch, mock_model, async_mock_model, explicit, async_, stream, error_type
):
    error = error_type("model failed")

    def fail():
        failing_local = "available in the debugger"
        assert failing_local
        raise error

    def execute(*args, **kwargs):
        fail()
        yield "unreachable"

    async def async_execute(*args, **kwargs):
        fail()
        yield "unreachable"

    model = async_mock_model if async_ else mock_model
    monkeypatch.setattr(model, "execute", async_execute if async_ else execute)
    post_mortem = Mock()
    monkeypatch.setattr("pdb.post_mortem", post_mortem)
    monkeypatch.delattr(sys, "_called_from_test")
    monkeypatch.delenv("LLM_RAISE_ERRORS", raising=False)

    args = (["prompt"] if explicit else []) + ["hello", "-m", "mock", "--pdb"]
    if async_:
        args.append("--async")
    if not stream:
        args.append("--no-stream")
    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 1
    assert result.output == "Error: model failed\n"
    post_mortem.assert_called_once()
    (traceback,) = post_mortem.call_args.args
    assert traceback is error.__traceback__
    while traceback.tb_next:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "fail"
    assert traceback.tb_frame.f_locals["failing_local"] == "available in the debugger"


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("raise_mode", ["normal", "pytest", "environment"])
def test_prompt_pdb_preserves_reraise(monkeypatch, mock_model, debug, raise_mode):
    error = RuntimeError("original error")

    def execute(*args, **kwargs):
        raise error
        yield "unreachable"

    monkeypatch.setattr(mock_model, "execute", execute)
    monkeypatch.setattr(sys, "_called_from_test", raise_mode == "pytest")
    monkeypatch.delenv("LLM_RAISE_ERRORS", raising=False)
    if raise_mode == "environment":
        monkeypatch.setenv("LLM_RAISE_ERRORS", "1")
    post_mortem = Mock()
    monkeypatch.setattr("pdb.post_mortem", post_mortem)
    args = ["hello", "-m", "mock"] + (["--pdb"] if debug else [])
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1
    if raise_mode == "normal":
        assert result.output == "Error: original error\n"
    else:
        assert result.exception is error
    assert post_mortem.call_count == int(debug)


@pytest.mark.parametrize("async_", [False, True])
@pytest.mark.parametrize("debug", [False, True])
def test_prompt_pdb_success(monkeypatch, mock_model, async_mock_model, async_, debug):
    model = async_mock_model if async_ else mock_model
    model.enqueue(["hello"])
    post_mortem = Mock()
    monkeypatch.setattr("pdb.post_mortem", post_mortem)
    args = ["hello", "-m", "mock"]
    if async_:
        args.append("--async")
    if debug:
        args.append("--pdb")
    result = CliRunner().invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "hello\n"
    post_mortem.assert_not_called()


def test_prompt_pdb_help():
    result = CliRunner().invoke(cli, ["prompt", "--help"])
    assert result.exit_code == 0
    assert "--pdb" in result.output
    assert "Enter debugger on prompt execution errors" in result.output


def test_prompt_pdb_model_lookup_error(monkeypatch):
    post_mortem = Mock()
    monkeypatch.setattr("pdb.post_mortem", post_mortem)
    result = CliRunner().invoke(cli, ["hello", "-m", "does-not-exist", "--pdb"])
    assert result.exit_code == 1
    assert "Unknown model" in result.output
    post_mortem.assert_not_called()


def test_prompt_pdb_interactive_quit():
    # Use a separate interpreter so pytest's own debugger wrapper does not
    # intercept pdb, and simulate a terminal so the prompt leaves stdin alone.
    script = """
import io
import sys
import llm
from llm.cli import cli
from llm.plugins import pm

class FailingModel(llm.Model):
    model_id = "pdb-test"
    def execute(self, *args, **kwargs):
        raise ValueError("inspect this failure")
        yield "unreachable"

class Plugin:
    @llm.hookimpl
    def register_models(self, register):
        register(FailingModel())

pm.register(Plugin())
sys.stdin = io.StringIO("q\\n")
sys.stdin.isatty = lambda: True
cli(["hello", "-m", "pdb-test", "--pdb"])
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1
    assert "(Pdb)" in result.stdout
    assert "execute()" in result.stdout
    assert result.stderr == "Error: inspect this failure\n"
