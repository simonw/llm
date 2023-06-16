from click.testing import CliRunner
from llm.cli import cli


def test_templates_list(templates_path):
    (templates_path / "one.yaml").write_text("template one", "utf-8")
    (templates_path / "two.yaml").write_text("template two", "utf-8")
    (templates_path / "three.yaml").write_text(
        "template three is very long " * 4, "utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["templates", "list"])
    assert result.exit_code == 0
    assert result.output == (
        "one   : template one\n"
        "three : template three is very long template three is very long template thre...\n"
        "two   : template two\n"
    )
