from click.testing import CliRunner
from llm_cli.cli import cli


def test_prompt_required():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli)
        assert result.exit_code == 2
        assert "Missing argument 'PROMPT'" in result.output

