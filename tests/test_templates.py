from click.testing import CliRunner
import json
from llm import Template
from llm.cli import cli
import os
from unittest import mock
import pathlib
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
        ("$one and $$2", None, None, {"one": 1}, "1 and $2", None, None),
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
    (templates_path / "invalid.yaml").write_text("system2: This is invalid", "utf-8")
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
    "args,expected,expected_error",
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
        # Options
        (
            ["-o", "temperature", "0.5", "--system", "in french"],
            {"system": "in french", "options": {"temperature": 0.5}},
            None,
        ),
        # -x/--extract should be persisted:
        (
            ["--system", "write python", "--extract"],
            {"system": "write python", "extract": True},
            None,
        ),
        # So should schemas (and should not sort properties)
        (
            [
                "--schema",
                '{"properties": {"b": {"type": "string"}, "a": {"type": "string"}}}',
            ],
            {
                "schema_object": {
                    "properties": {"b": {"type": "string"}, "a": {"type": "string"}}
                }
            },
            None,
        ),
        # And fragments and system_fragments
        (
            ["--fragment", "f1.txt", "--system-fragment", "https://example.com/f2.txt"],
            {
                "fragments": ["f1.txt"],
                "system_fragments": ["https://example.com/f2.txt"],
            },
            None,
        ),
        # And attachments and attachment_types
        (
            ["--attachment", "a.txt", "--attachment-type", "b.txt", "text/plain"],
            {
                "attachments": ["a.txt"],
                "attachment_types": [{"type": "text/plain", "value": "b.txt"}],
            },
            None,
        ),
    ),
)
def test_templates_prompt_save(templates_path, args, expected, expected_error):
    assert not (templates_path / "saved.yaml").exists()
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Create a file to test attachment
        pathlib.Path("a.txt").write_text("attachment", "utf-8")
        pathlib.Path("b.txt").write_text("attachment type", "utf-8")
        result = runner.invoke(cli, args + ["--save", "saved"], catch_exceptions=False)
    if not expected_error:
        assert result.exit_code == 0
        yaml_data = yaml.safe_load((templates_path / "saved.yaml").read_text("utf-8"))
        # Adjust attachment and attachment_types paths to be just the filename
        if "attachments" in yaml_data:
            yaml_data["attachments"] = [
                os.path.basename(path) for path in yaml_data["attachments"]
            ]
        for item in yaml_data.get("attachment_types", []):
            item["value"] = os.path.basename(item["value"])
        assert yaml_data == expected
    else:
        assert result.exit_code == 1
        assert expected_error in result.output


def test_templates_error_on_missing_schema(templates_path):
    runner = CliRunner()
    runner.invoke(
        cli, ["the-prompt", "--save", "prompt_no_schema"], catch_exceptions=False
    )
    # This should complain about no schema
    result = runner.invoke(
        cli, ["hi", "--schema", "t:prompt_no_schema"], catch_exceptions=False
    )
    assert result.output == "Error: Template 'prompt_no_schema' has no schema\n"
    # And this is just an invalid template
    result2 = runner.invoke(
        cli, ["hi", "--schema", "t:bad_template"], catch_exceptions=False
    )
    assert result2.output == "Error: Invalid template: bad_template\n"


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize(
    "template,input_text,extra_args,expected_model,expected_input,expected_error,expected_options",
    (
        (
            "'Summarize this: $input'",
            "Input text",
            [],
            "gpt-4o-mini",
            "Summarize this: Input text",
            None,
            None,
        ),
        (
            "prompt: 'Summarize this: $input'\nmodel: gpt-4",
            "Input text",
            [],
            "gpt-4",
            "Summarize this: Input text",
            None,
            None,
        ),
        (
            "prompt: 'Summarize this: $input'",
            "Input text",
            ["-m", "4"],
            "gpt-4",
            "Summarize this: Input text",
            None,
            None,
        ),
        # -s system prompt should over-ride template system prompt
        pytest.param(
            "boo",
            "Input text",
            ["-s", "custom system"],
            "gpt-4o-mini",
            [
                {"role": "system", "content": "custom system"},
                {"role": "user", "content": "boo\nInput text"},
            ],
            None,
            None,
            marks=pytest.mark.httpx_mock(),
        ),
        pytest.param(
            "prompt: 'Say $hello'",
            "Input text",
            [],
            None,
            None,
            "Error: Missing variables: hello",
            None,
            marks=pytest.mark.httpx_mock(),
        ),
        # Template generated prompt should combine with CLI prompt
        (
            "prompt: 'Say $hello'",
            "Input text",
            ["-p", "hello", "Blah"],
            "gpt-4o-mini",
            "Say Blah\nInput text",
            None,
            None,
        ),
        (
            "prompt: 'Say pelican'",
            "",
            [],
            "gpt-4o-mini",
            "Say pelican",
            None,
            None,
        ),
        # Template with just a system prompt
        (
            "system: 'Summarize this'",
            "Input text",
            [],
            "gpt-4o-mini",
            [
                {"content": "Summarize this", "role": "system"},
                {"content": "Input text", "role": "user"},
            ],
            None,
            None,
        ),
        # Options
        (
            "prompt: 'Summarize this: $input'\noptions:\n  temperature: 0.5",
            "Input text",
            [],
            "gpt-4o-mini",
            "Summarize this: Input text",
            None,
            {"temperature": 0.5},
        ),
        # Should be over-ridden by CLI
        (
            "prompt: 'Summarize this: $input'\noptions:\n  temperature: 0.5",
            "Input text",
            ["-o", "temperature", "0.7"],
            "gpt-4o-mini",
            "Summarize this: Input text",
            None,
            {"temperature": 0.7},
        ),
    ),
)
def test_execute_prompt_with_a_template(
    templates_path,
    mocked_openai_chat,
    template,
    input_text,
    extra_args,
    expected_model,
    expected_input,
    expected_error,
    expected_options,
):
    (templates_path / "template.yaml").write_text(template, "utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--no-stream", "-t", "template"]
        + ([input_text] if input_text else [])
        + extra_args,
        catch_exceptions=False,
    )
    if isinstance(expected_input, str):
        expected_messages = [{"role": "user", "content": expected_input}]
    else:
        expected_messages = expected_input

    if expected_error is None:
        assert result.exit_code == 0
        last_request = mocked_openai_chat.get_requests()[-1]
        expected_data = {
            "model": expected_model,
            "messages": expected_messages,
            "stream": False,
        }
        if expected_options:
            expected_data.update(expected_options)
        assert json.loads(last_request.content) == expected_data
    else:
        assert result.exit_code == 1
        assert result.output.strip() == expected_error
        mocked_openai_chat.reset()


@pytest.mark.parametrize(
    "template,expected",
    (
        (
            "system: system\nprompt: prompt",
            {
                "prompt": "prompt",
                "system": "system",
                "attachments": [],
                "stream": True,
                "previous": [],
            },
        ),
        (
            "prompt: |\n  This is\n  ```\n  code to extract\n  ```",
            {
                "prompt": "This is\n```\ncode to extract\n```",
                "system": "",
                "attachments": [],
                "stream": True,
                "previous": [],
            },
        ),
        # Now try that with extract: true
        (
            'extract: true\nprompt: |\n  {"raw": "This is\\n```\\ncode to extract\\n```"}',
            "code to extract",
        ),
    ),
)
def test_execute_prompt_from_template_url(httpx_mock, template, expected):
    httpx_mock.add_response(
        url="https://example.com/prompt.yaml",
        method="GET",
        text=template,
        status_code=200,
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-t", "https://example.com/prompt.yaml", "-m", "echo"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    if isinstance(expected, dict):
        assert json.loads(result.output.strip()) == expected
    else:
        assert result.output.strip() == expected


def test_execute_prompt_from_template_path():
    runner = CliRunner()
    with runner.isolated_filesystem() as temp_dir:
        path = pathlib.Path(temp_dir) / "my-template.yaml"
        path.write_text("system: system\nprompt: prompt", "utf-8")
        result = runner.invoke(
            cli,
            ["-t", str(path), "-m", "echo"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {
            "prompt": "prompt",
            "system": "system",
            "attachments": [],
            "stream": True,
            "previous": [],
        }
