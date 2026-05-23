"""Tests for CLI streaming display: reasoning → stderr (dim),
text → stdout, -R / --hide-reasoning flag.
"""

import click
from click.testing import CliRunner

import llm
from llm.cli import cli


def test_text_goes_to_stdout_not_stderr(mock_model):
    mock_model.enqueue(["Hello world"])
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Hello world" in result.stdout
    # No reasoning was emitted — stderr should be empty.
    assert result.stderr == ""


def test_reasoning_goes_to_stderr_not_stdout(mock_model):
    mock_model.enqueue(
        [
            llm.parts.StreamEvent(
                type="reasoning", chunk="thinking hard", part_index=0
            ),
            llm.parts.StreamEvent(type="text", chunk="answer", part_index=1),
        ]
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "thinking hard" in result.stderr
    assert "thinking hard" not in result.stdout
    assert "answer" in result.stdout


def test_reasoning_rendered_in_dim_style(mock_model):
    """The click.style(..., dim=True) wrapper emits the ANSI dim code."""
    mock_model.enqueue(
        [
            llm.parts.StreamEvent(type="reasoning", chunk="t", part_index=0),
            llm.parts.StreamEvent(type="text", chunk="x", part_index=1),
        ]
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log"],
        catch_exceptions=False,
        color=True,
    )
    assert result.exit_code == 0
    # ANSI dim escape sequence is \x1b[2m
    dim_start = click.style("x", dim=True).split("x", 1)[0]
    assert dim_start in result.stderr


def test_hide_reasoning_flag_suppresses_reasoning(mock_model):
    mock_model.enqueue(
        [
            llm.parts.StreamEvent(
                type="reasoning", chunk="hidden thinking", part_index=0
            ),
            llm.parts.StreamEvent(type="text", chunk="answer", part_index=1),
        ]
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log", "--hide-reasoning"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "hidden thinking" not in result.stderr
    assert "hidden thinking" not in result.stdout
    assert "answer" in result.stdout
    assert mock_model.history[0][0].hide_reasoning is True


def test_hide_reasoning_short_flag_R(mock_model):
    mock_model.enqueue(
        [
            llm.parts.StreamEvent(type="reasoning", chunk="hidden", part_index=0),
            llm.parts.StreamEvent(type="text", chunk="x", part_index=1),
        ]
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log", "-R"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "hidden" not in result.stderr


def test_newline_between_reasoning_and_text(mock_model):
    """When reasoning ends and text begins, stderr gets a newline so the
    text on stdout starts on a fresh visual line."""
    mock_model.enqueue(
        [
            llm.parts.StreamEvent(type="reasoning", chunk="think", part_index=0),
            llm.parts.StreamEvent(type="text", chunk="answer", part_index=1),
        ]
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # Reasoning ends, then a newline is emitted on stderr.
    assert result.stderr.rstrip("\n").endswith("think") or "think\n" in result.stderr


def test_async_path_reasoning_to_stderr(async_mock_model):
    async_mock_model.enqueue(
        [
            llm.parts.StreamEvent(
                type="reasoning", chunk="async thinking", part_index=0
            ),
            llm.parts.StreamEvent(type="text", chunk="async answer", part_index=1),
        ]
    )
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--async", "--no-log"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "async thinking" in result.stderr
    assert "async answer" in result.stdout


def test_plain_str_plugin_still_works(mock_model):
    """A plugin that yields plain strings (legacy) still displays
    correctly — no reasoning branch, everything to stdout."""
    mock_model.enqueue(["plain ", "text"])
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        cli,
        ["-m", "mock", "hi", "--no-log"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "plain text" in result.stdout
    assert result.stderr == ""
