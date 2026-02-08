"""Tests for the --render markdown rendering feature."""

from click.testing import CliRunner
from unittest import mock
import llm.cli
import os
import pytest
import subprocess
import sys


# --- Unit tests for _render_output ---


class TestRenderOutputUnit:
    """Unit tests for the _render_output helper function."""

    def test_skips_when_not_tty(self):
        """Should return immediately when stdout is not a TTY."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            with mock.patch("subprocess.run") as mock_run:
                llm.cli._render_output("# Hello", renderer="glow")
                mock_run.assert_not_called()

    def test_skips_when_no_renderer(self):
        """Should return immediately when renderer is None/empty."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            with mock.patch("subprocess.run") as mock_run:
                llm.cli._render_output("# Hello", renderer=None)
                mock_run.assert_not_called()
                llm.cli._render_output("# Hello", renderer="")
                mock_run.assert_not_called()

    def test_skips_when_renderer_not_found(self):
        """Should return immediately when renderer binary is not on PATH."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            with mock.patch("shutil.which", return_value=None):
                with mock.patch("subprocess.run") as mock_run:
                    llm.cli._render_output("# Hello", renderer="glow")
                    mock_run.assert_not_called()

    def test_glow_command_includes_style_dark(self):
        """glow must be called with -s dark to force styled output in pipe."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            mock_stdout.write = mock.Mock()
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/glow"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    mock_ts.return_value = os.terminal_size((100, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="\033[1mHello\033[0m\n"
                        )
                        llm.cli._render_output("# Hello", renderer="glow")
                        cmd = mock_run.call_args[0][0]
                        assert cmd[0] == "glow"
                        assert "-s" in cmd
                        assert "dark" in cmd
                        assert "-w" in cmd
                        assert "100" in cmd

    def test_glow_env_has_clicolor_force(self):
        """subprocess must pass CLICOLOR_FORCE=1 in environment."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            mock_stdout.write = mock.Mock()
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/glow"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    mock_ts.return_value = os.terminal_size((80, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="rendered\n"
                        )
                        llm.cli._render_output("# Hello", renderer="glow")
                        env = mock_run.call_args[1]["env"]
                        assert env["CLICOLOR_FORCE"] == "1"

    def test_bat_command_includes_color_always(self):
        """bat must be called with --color=always to force ANSI output in pipe."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            mock_stdout.write = mock.Mock()
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/bat"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    mock_ts.return_value = os.terminal_size((80, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="rendered\n"
                        )
                        llm.cli._render_output("# Hello", renderer="bat")
                        cmd = mock_run.call_args[0][0]
                        assert cmd[0] == "bat"
                        assert "--color=always" in cmd

    def test_fallback_on_renderer_failure(self, capsys):
        """When renderer exits non-zero, should reprint raw text."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            mock_stdout.write = mock.Mock()
            mock_stdout.flush = mock.Mock()
            # We need print() to go somewhere we can check
            printed = []
            with mock.patch("builtins.print", side_effect=lambda *a, **kw: printed.append(a)):
                with mock.patch("shutil.which", return_value="/usr/bin/glow"):
                    with mock.patch("shutil.get_terminal_size") as mock_ts:
                        mock_ts.return_value = os.terminal_size((80, 40))
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.return_value = subprocess.CompletedProcess(
                                args=[], returncode=1, stdout="", stderr="error"
                            )
                            llm.cli._render_output("# Hello", renderer="glow")
                            # Should have printed raw text as fallback
                            assert any("# Hello" in str(p) for p in printed)

    def test_ansi_clear_sequence_written(self):
        """Should write ANSI escape to move cursor up and clear."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            write_calls = []
            mock_stdout.write = mock.Mock(side_effect=lambda s: write_calls.append(s))
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/glow"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    mock_ts.return_value = os.terminal_size((80, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="rendered\n"
                        )
                        llm.cli._render_output("Line1\nLine2\nLine3", renderer="glow")
                        # First write should be ANSI clear: \033[3F\033[J (3 lines)
                        assert len(write_calls) >= 1
                        assert "\033[3F" in write_calls[0]
                        assert "\033[J" in write_calls[0]

    def test_line_count_wrapping(self):
        """Long lines should count as multiple terminal lines."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            write_calls = []
            mock_stdout.write = mock.Mock(side_effect=lambda s: write_calls.append(s))
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/glow"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    # Terminal width 10, line of 25 chars = 3 lines
                    mock_ts.return_value = os.terminal_size((10, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="rendered\n"
                        )
                        llm.cli._render_output("a" * 25, renderer="glow")
                        # 25 chars / 10 width = ceil(2.5) = 3 lines
                        assert "\033[3F" in write_calls[0]

    def test_env_var_fallback(self):
        """When renderer=None, should check LLM_RENDER env var."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            mock_stdout.write = mock.Mock()
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/glow"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    mock_ts.return_value = os.terminal_size((80, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="rendered\n"
                        )
                        with mock.patch.dict(os.environ, {"LLM_RENDER": "glow"}):
                            llm.cli._render_output("# Hello", renderer=None)
                            mock_run.assert_called_once()
                            cmd = mock_run.call_args[0][0]
                            assert cmd[0] == "glow"

    def test_custom_renderer(self):
        """Non-glow/bat renderer should be split into command parts."""
        with mock.patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            mock_stdout.write = mock.Mock()
            mock_stdout.flush = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/mdcat"):
                with mock.patch("shutil.get_terminal_size") as mock_ts:
                    mock_ts.return_value = os.terminal_size((80, 40))
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="rendered\n"
                        )
                        llm.cli._render_output("# Hello", renderer="mdcat --columns 80")
                        cmd = mock_run.call_args[0][0]
                        assert cmd == ["mdcat", "--columns", "80"]


# --- CLI integration tests ---


class TestRenderCLI:
    """Integration tests for the --render CLI option."""

    def test_render_option_in_prompt_help(self):
        runner = CliRunner()
        result = runner.invoke(llm.cli.cli, ["prompt", "--help"])
        assert "--render" in result.output
        assert "markdown formatter" in result.output

    def test_render_option_in_chat_help(self):
        runner = CliRunner()
        result = runner.invoke(llm.cli.cli, ["chat", "--help"])
        assert "--render" in result.output
        assert "markdown formatter" in result.output

    def test_render_streaming_buffers_and_calls_renderer(self, mock_model):
        """In streaming mode, chunks should be buffered and passed to _render_output."""
        mock_model.enqueue(["# Hello ", "World\n", "- item 1\n", "- item 2"])
        runner = CliRunner()
        with mock.patch("llm.cli._render_output") as mock_render:
            result = runner.invoke(
                llm.cli.cli,
                ["-m", "mock", "--render", "glow", "test prompt"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            # _render_output should have been called with joined chunks
            mock_render.assert_called_once()
            text_arg = mock_render.call_args[0][0]
            assert text_arg == "# Hello World\n- item 1\n- item 2"
            assert mock_render.call_args[1]["renderer"] == "glow"

    def test_render_no_stream_calls_renderer(self, mock_model):
        """In non-streaming mode, complete text should be passed to _render_output."""
        mock_model.enqueue(["# Full response"])
        runner = CliRunner()
        with mock.patch("llm.cli._render_output") as mock_render:
            result = runner.invoke(
                llm.cli.cli,
                ["-m", "mock", "--render", "bat", "--no-stream", "test"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            mock_render.assert_called_once()
            assert mock_render.call_args[1]["renderer"] == "bat"

    def test_render_not_called_without_flag(self, mock_model):
        """Without --render flag, _render_output should not be called."""
        mock_model.enqueue(["hello"])
        runner = CliRunner()
        with mock.patch("llm.cli._render_output") as mock_render:
            result = runner.invoke(
                llm.cli.cli,
                ["-m", "mock", "test"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            mock_render.assert_not_called()

    def test_render_env_var_activates(self, mock_model, monkeypatch):
        """LLM_RENDER env var should activate rendering."""
        mock_model.enqueue(["hello"])
        monkeypatch.setenv("LLM_RENDER", "glow")
        runner = CliRunner()
        with mock.patch("llm.cli._render_output") as mock_render:
            result = runner.invoke(
                llm.cli.cli,
                ["-m", "mock", "test"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            mock_render.assert_called_once()
            assert mock_render.call_args[1]["renderer"] == "glow"

    @pytest.mark.xfail(sys.platform == "win32", reason="Expected to fail on Windows")
    def test_render_chat_mode(self, mock_model, logs_db):
        """Chat mode should call _render_output for each response."""
        mock_model.enqueue(["response one"])
        mock_model.enqueue(["response two"])
        runner = CliRunner()
        with mock.patch("llm.cli._render_output") as mock_render:
            result = runner.invoke(
                llm.cli.cli,
                ["chat", "-m", "mock", "--render", "glow"],
                input="hello\nworld\nquit\n",
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert mock_render.call_count == 2
            # First call with "response one", second with "response two"
            first_text = mock_render.call_args_list[0][0][0]
            second_text = mock_render.call_args_list[1][0][0]
            assert first_text == "response one"
            assert second_text == "response two"

    def test_output_contains_raw_text_always(self, mock_model):
        """Raw text should always be in output (CliRunner is non-TTY so render skips)."""
        mock_model.enqueue(["# Hello World"])
        runner = CliRunner()
        result = runner.invoke(
            llm.cli.cli,
            ["-m", "mock", "--render", "glow", "test"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "# Hello World" in result.output
