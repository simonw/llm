from click.testing import CliRunner
from llm.cli import cli
import os
from unittest import mock
import pytest


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


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize(
    "template,extra_args,expected_model,expected_input",
    (
        ("'Summarize this: $input'", [], "gpt-3.5-turbo", "Summarize this: Input text"),
        (
            "prompt: 'Summarize this: $input'\nmodel: gpt-4",
            [],
            "gpt-4",
            "Summarize this: Input text",
        ),
        (
            "prompt: 'Summarize this: $input'",
            ["-m", "4"],
            "gpt-4",
            "Summarize this: Input text",
        ),
    ),
)
def test_template_basic(
    templates_path, mocked_openai, template, extra_args, expected_model, expected_input
):
    (templates_path / "template.yaml").write_text(template, "utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--no-stream", "-t", "template", "Input text"] + extra_args,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert mocked_openai.last_request.json() == {
        "model": expected_model,
        "messages": [{"role": "user", "content": expected_input}],
    }
