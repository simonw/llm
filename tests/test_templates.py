from click.testing import CliRunner
import click
import json
from llm import Template, hookimpl
from llm.cli import cli, load_template
from llm.plugins import pm
import os
from unittest import mock
import pytest
import yaml


class CustomTemplate(Template):
    """A custom template type for testing."""
    type: str = "custom"

    def evaluate(self, input: str, params=None):
        prompt, system = super().evaluate(input, params)
        if prompt:
            prompt = f"CUSTOM: {prompt}"
        if system:
            system = f"CUSTOM: {system}"
        return prompt, system

    def stringify(self):
        parts = []
        if self.prompt:
            parts.append(f"custom prompt: {self.prompt}")
        if self.system:
            parts.append(f"custom system: {self.system}")
        return " ".join(parts)


class MockPlugin:
    __name__ = "MockPlugin"

    @hookimpl
    def register_template_types(self):
        return {
            "custom": CustomTemplate
        }


@pytest.fixture
def register_custom_template(monkeypatch):
    pm.register(MockPlugin(), name="mock-plugin")
    try:
        yield
    finally:
        pm.unregister(name="mock-plugin")


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


@pytest.mark.parametrize(
    "template_yaml,expected_type,expected_prompt,expected_system,expected_error",
    (
        (
            """
            type: custom
            prompt: Hello $input
            system: Be helpful
            """,
            CustomTemplate,
            "CUSTOM: Hello world",
            "CUSTOM: Be helpful",
            None,
        ),
        (
            """
            type: unknown
            prompt: Hello $input
            """,
            None,
            None,
            None,
            "Unknown template type: unknown",
        ),
        (
            "Hello $input",
            Template,
            "Hello world",
            None,
            None,
        ),
        (
            """
            prompt: Hello $input
            system: Be helpful
            """,
            Template,
            "Hello world",
            "Be helpful",
            None,
        ),
    ),
)
def test_template_types(
    register_custom_template,
    templates_path,
    template_yaml,
    expected_type,
    expected_prompt,
    expected_system,
    expected_error,
):
    (templates_path / "test.yaml").write_text(template_yaml, "utf-8")
    if expected_error:
        with pytest.raises(click.ClickException, match=expected_error):
            load_template("test")
    else:
        template = load_template("test")
        assert isinstance(template, expected_type)
        if expected_type == CustomTemplate:
            assert template.type == "custom"
        prompt, system = template.evaluate("world")
        assert prompt == expected_prompt
        assert system == expected_system


def test_templates_list_no_templates_found():
    runner = CliRunner()
    result = runner.invoke(cli, ["templates", "list"])
    assert result.exit_code == 0
    assert result.output == ""


@pytest.mark.parametrize("args", (["templates", "list"], ["templates"]))
@pytest.mark.usefixtures("register_custom_template")
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
    (templates_path / "custom.yaml").write_text(
        "type: custom\nprompt: Hello $input", "utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    assert len(lines) == 7
    assert lines[0] == "both   : system: summarize this prompt: $input"
    assert lines[1] == "custom : custom prompt: Hello $input"
    assert lines[2] == "four   : this one has newlines in it"
    assert lines[3] == "one    : template one"
    assert lines[4] == "sys    : system: Summarize this"
    assert lines[5].startswith("three  : template three is very long template three is very long template")
    assert lines[5].endswith("...")
    assert lines[6] == "two    : template two"


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
        # -x/--extract should be persisted:
        (
            ["--system", "write python", "--extract"],
            {"system": "write python", "extract": True},
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
            marks=pytest.mark.httpx_mock(),
        ),
        pytest.param(
            "prompt: 'Say $hello'",
            [],
            None,
            None,
            "Error: Missing variables: hello",
            marks=pytest.mark.httpx_mock(),
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


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "X"})
@pytest.mark.parametrize(
    "template,extra_args,expected_model,expected_input,expected_error",
    (
        (
            "type: custom\nprompt: 'Say $hello'",
            ["-p", "hello", "Blah"],
            "gpt-4o-mini",
            "CUSTOM: Say Blah",
            None,
        ),
    ),
)
def test_template_basic_custom(
    register_custom_template,
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
