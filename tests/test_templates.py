from click.testing import CliRunner
from llm import Template
from llm.cli import cli
import os
from unittest import mock
import pytest


@pytest.mark.parametrize(
    "prompt,system,params,expected_prompt,expected_system,expected_error",
    (
        ("S: $input", None, {}, "S: input", None, None),
        ("S: $input", "system", {}, "S: input", "system", None),
        ("No vars", None, {}, "No vars", None, None),
        ("$one and $two", None, {}, None, None, "Missing variables: one, two"),
        ("$one and $two", None, {"one": 1, "two": 2}, "1 and 2", None, None),
    ),
)
def test_template_execute(
    prompt, system, params, expected_prompt, expected_system, expected_error
):
    t = Template(name="t", prompt=prompt, system=system)
    if expected_error:
        with pytest.raises(Template.MissingVariables) as ex:
            prompt, system = t.execute("input", params)
        assert ex.value.args[0] == expected_error
    else:
        prompt, system = t.execute("input", params)
        assert prompt == expected_prompt
        assert system == expected_system


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
    "template,extra_args,expected_model,expected_input,expected_error",
    (
        (
            "'Summarize this: $input'",
            [],
            "gpt-3.5-turbo",
            "Summarize this: Input text",
            None,
        ),
        (
            "prompt: 'Summarize this: $input'\nmodel: gpt-4",
            [],
            "gpt-4",
            "Summarize this: Input text",
            None,
        ),
        (
            "prompt: 'Summarize this: $input'",
            ["-m", "4"],
            "gpt-4",
            "Summarize this: Input text",
            None,
        ),
        (
            "boo",
            ["--system", "s"],
            None,
            None,
            "Error: Cannot use -t/--template and --system together",
        ),
        (
            "prompt: 'Say $hello'",
            [],
            None,
            None,
            "Error: Missing variables: hello",
        ),
        (
            "prompt: 'Say $hello'",
            ["-p", "hello", "Blah"],
            "gpt-3.5-turbo",
            "Say Blah",
            None,
        ),
    ),
)
def test_template_basic(
    templates_path,
    mocked_openai,
    template,
    extra_args,
    expected_model,
    expected_input,
    expected_error,
):
    (templates_path / "template.yaml").write_text(template, "utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--no-stream", "-t", "template", "Input text"] + extra_args,
        catch_exceptions=False,
    )
    if expected_error is None:
        assert result.exit_code == 0
        assert mocked_openai.last_request.json() == {
            "model": expected_model,
            "messages": [{"role": "user", "content": expected_input}],
        }
    else:
        assert result.exit_code == 1
        assert result.output.strip() == expected_error
