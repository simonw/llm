from click.testing import CliRunner
import subprocess
import sys
from unittest.mock import MagicMock, patch

import llm.cli as cli
import pytest


@pytest.fixture
def runner():
    return CliRunner()


def test_install_invokes_pip_subprocess(runner):
    # https://github.com/simonw/llm/issues/1811
    # pip must not be run in-process (runpy.run_module) because pip mutates
    # global interpreter state and is not thread-safe. The install command
    # should invoke [sys.executable, "-m", "pip", "install", ...] instead.
    with patch("llm.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit) as excinfo:
            cli.install.callback(
                packages=("llm-foo",),
                upgrade=False,
                editable=None,
                force_reinstall=False,
                no_cache_dir=False,
                pre=False,
            )
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "llm-foo"]
        )
        assert excinfo.value.code == 0


def test_install_flags_forwarded(runner):
    with patch("llm.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit):
            cli.install.callback(
                packages=("llm-foo", "llm-bar"),
                upgrade=True,
                editable=".",
                force_reinstall=True,
                no_cache_dir=True,
                pre=True,
            )
    args = mock_run.call_args[0][0]
    assert args[:3] == [sys.executable, "-m", "pip"]
    assert args[3] == "install"
    assert "--upgrade" in args
    assert "--editable" in args and "." in args
    assert "--force-reinstall" in args
    assert "--no-cache-dir" in args
    assert "--pre" in args
    assert "llm-foo" in args and "llm-bar" in args


def test_install_exit_code_propagates(runner):
    # A failing pip should make llm exit non-zero, not return cleanly.
    with patch("llm.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=2)
        with pytest.raises(SystemExit) as excinfo:
            cli.install.callback(
                packages=("llm-foo",),
                upgrade=False,
                editable=None,
                force_reinstall=False,
                no_cache_dir=False,
                pre=False,
            )
        assert excinfo.value.code == 2


def test_uninstall_invokes_pip_subprocess(runner):
    with patch("llm.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit):
            cli.uninstall.callback(packages=("llm-foo",), yes=True)
    args = mock_run.call_args[0][0]
    assert args[:3] == [sys.executable, "-m", "pip"]
    assert args[3:] == ["uninstall", "llm-foo", "-y"]


def test_uninstall_asks_without_yes(runner):
    with patch("llm.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit):
            cli.uninstall.callback(packages=("llm-foo",), yes=False)
    args = mock_run.call_args[0][0]
    assert args == [sys.executable, "-m", "pip", "uninstall", "llm-foo"]


def test_pip_not_run_in_process(runner):
    # Guard against a regression to runpy.run_module("pip"): importing runpy
    # in llm.cli would be a smell, and calling run_module must never happen.
    with patch("llm.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("runpy.run_module") as mock_run_module, pytest.raises(SystemExit):
            cli.install.callback(
                packages=("llm-foo",),
                upgrade=False,
                editable=None,
                force_reinstall=False,
                no_cache_dir=False,
                pre=False,
            )
        mock_run_module.assert_not_called()
