import pytest
from click.shell_completion import BashComplete, FishComplete, ZshComplete
from click.testing import CliRunner

from llm.cli import cli


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completions_matches_click(shell, user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["completions", shell])
    expected = runner.invoke(
        cli, [], prog_name="llm", env={"_LLM_COMPLETE": f"{shell}_source"}
    )

    assert result.exit_code == 0, result.output
    assert expected.exit_code == 0, expected.output
    assert result.stdout == expected.stdout
    assert "_llm_completion" in result.stdout
    assert f"_LLM_COMPLETE={shell}_complete" in result.stdout
    assert not user_path.listdir()


@pytest.mark.parametrize(
    "shell,completion_class",
    [("bash", BashComplete), ("zsh", ZshComplete), ("fish", FishComplete)],
)
def test_completions_uses_root_command(shell, completion_class, monkeypatch):
    calls = []

    def source(self):
        calls.append((self.cli, self.ctx_args, self.prog_name, self.complete_var))
        return "# completion script"

    monkeypatch.setattr(completion_class, "source", source)
    result = CliRunner().invoke(cli, ["completions", shell])

    assert result.exit_code == 0, result.output
    assert result.output == "# completion script"
    assert calls == [(cli, {}, "llm", "_LLM_COMPLETE")]


@pytest.mark.parametrize(
    "args,error",
    [
        ([], "Missing argument"),
        (["unknown"], "Invalid value"),
        (["bash; echo unexpected"], "Invalid value"),
        (["bash", "zsh"], "Got unexpected extra argument"),
    ],
)
def test_completions_invalid_arguments(args, error):
    result = CliRunner().invoke(cli, ["completions"] + args)

    assert result.exit_code == 2
    assert error in result.output


def test_completions_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["completions", "--help"])

    assert result.exit_code == 0
    assert "bash|zsh|fish" in result.output
    assert "Generate a shell completion script" in result.output
    assert "completions" in runner.invoke(cli, ["--help"]).output
