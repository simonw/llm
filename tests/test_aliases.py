from click.testing import CliRunner
from llm.cli import cli


def test_aliases_list():
    runner = CliRunner()
    result = runner.invoke(cli, ["aliases", "list"])
    assert result.exit_code == 0
    assert result.output == (
        "3.5 = gpt-3.5-turbo\n"
        "chatgpt = gpt-3.5-turbo\n"
        "chatgpt-16k = gpt-3.5-turbo-16k\n"
        "3.5-16k = gpt-3.5-turbo-16k\n"
        "4 = gpt-4\n"
        "gpt4 = gpt-4\n"
        "4-32k = gpt-4-32k\n"
    )
