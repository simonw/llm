from click.testing import CliRunner
import json
from llm import Template
from llm.cli import cli
import os
from unittest import mock
import pytest
import yaml


@pytest.mark.parametrize(
    "prompt,system,defaults,params,expected_prompt,expected_system,expected_error",
    (
        ("S: $input", None, None, {}, "S: input", None, None),
        ("S: $input", "system", None, {}, "S: input", "system", None),
        ("No vars", None, None, {}, "No vars", None, None),
        ("$one and $two", None, None, {}, None, None, "Missing variables: one, two"),
        ("$one and $two", None, None, {"one": 1, "two": 2}, "1 and 2", None, None),
        ("$one and $two", None, {"one": 1}, {"two": 2}, "1 and 2", None, None),
        (
            "$one and $two",
            None,
            {"one": 99},
            {"one": 1, "two": 2},
            "1 and 2",
            None,
            None,
        ),
    ),
)
def test_template_evaluate(
    prompt, system, defaults, params, expected_prompt, expected_system, expected_error
):
    t = Template(name="t", prompt=prompt, system=system, defaults=defaults)
    if expected_error:
        with pytest.raises(Template.MissingVariables) as ex:
            prompt, system = t.evaluate("input", params)
        assert ex.value.args[0] == expected_error
    else:
        prompt, system = t.evaluate("input", params)
        assert prompt == expected_prompt
        assert system == expected_system


def test_templates_list_no_templates_found():
    runner = CliRunner()
    result = runner.invoke(cli, ["templates", "list"])
    assert result.exit_code == 0
    assert result.output == ""


@pytest.mark.parametrize("args", (["templates", "list"], ["templates"]))
def test_templates_list(templates_path, args):
    (templates_path / "one.yaml").write_text("template one", "utf-8")
    (templates_path / "two.yaml").write_text("template two", "utf-8")
    (templates_path / "three.yaml").write_text(
        "template three is very long " * 4, "utf-8"
    )
    (templates_path / "four.yaml").write_text(
        "'this one\n\nhas newlines in it'", "utf-8"
    )
    (templates_path / "both.yaml").write_text(
        "system: summarize this\nprompt: $input", "utf-8"
    )
    (templates_path / "sys.yaml").write_text("system: Summarize this", "utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    assert result.output == (
        "both  : system: summarize this prompt: $input\n"
        "four  : this one has newlines in it\n"
        "one   : template one\n"
        "sys   : system: Summarize this\n"
        "three : template three is very long template three is very long template thre...\n"
        "two   : template two\n"
    )


@pytest.mark.parametrize(
    "args,expected_prompt,expected_error",
    (
        (["-m", "gpt4", "hello"], {"model": "gpt-4", "prompt": "hello"}, None),
        (["hello $foo"], {"prompt": "hello $foo"}, None),
        (["--system", "system"], {"system": "system"}, None),
        (["-t", "template"], None, "--save cannot be used with --template"),
        (["--continue"], None, "--save cannot be used with --continue"),
        (["--cid", "123"], None, "--save cannot be used with --cid"),
        (["--conversation", "123"], None, "--save cannot be used with --cid"),
        (
            ["Say hello as $name", "-p", "name", "default-name"],
            {"prompt": "Say hello as $name", "defaults": {"name": "default-name"}},
            None,
        ),
    ),
)
def test_templates_prompt_save(templates_path, args, expected_prompt, expected_error):
    assert not (templates_path / "saved.yaml").exists()
    runner = CliRunner()
    result = runner.invoke(cli, args + ["--save", "saved"], catch_exceptions=False)
    if not expected_error:
        assert result.exit_code == 0
        assert (
            yaml.safe_load((templates_path / "saved.yaml").read_text("utf-8"))
            == expected_prompt
        )
    else:
        assert result.exit_code == 1
        assert expected_error in result.output


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize(
    "template,extra_args,expected_model,expected_input,expected_error",
    (
        (
            "'Summarize this: $input'",
            [],
            "gpt-4o-mini",
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
        pytest.param(
            "boo",
            ["-s", "s"],
            None,
            None,
            "Error: Cannot use -t/--template and --system together",
            marks=pytest.mark.httpx_mock(assert_all_responses_were_requested=False),
        ),
        pytest.param(
            "prompt: 'Say $hello'",
            [],
            None,
            None,
            "Error: Missing variables: hello",
            marks=pytest.mark.httpx_mock(assert_all_responses_were_requested=False),
        ),
        (
            "prompt: 'Say $hello'",
            ["-p", "hello", "Blah"],
            "gpt-4o-mini",
            "Say Blah",
            None,
        ),
    ),
)
def test_template_basic(
    templates_path,
    mocked_openai_chat,
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
        last_request = mocked_openai_chat.get_requests()[-1]
        assert json.loads(last_request.content) == {
            "model": expected_model,
            "messages": [{"role": "user", "content": expected_input}],
            "stream": False,
        }
    else:
        assert result.exit_code == 1
        assert result.output.strip() == expected_error
        mocked_openai_chat.reset()
