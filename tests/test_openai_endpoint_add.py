import json

import pytest
import yaml
from click.testing import CliRunner

import llm
from llm.cli import cli


def _invoke(*args):
    return CliRunner().invoke(
        cli, ["openai", "endpoint", *args], catch_exceptions=False
    )


def _read_yaml(user_path):
    return yaml.safe_load((user_path / "extra-openai-models.yaml").read_text("utf-8"))


def test_endpoint_add_minimal(user_path):
    result = _invoke("add", "http://localhost:8080", "-m", "orca-mini-3b")
    assert result.exit_code == 0, result.output
    path = user_path / "extra-openai-models.yaml"
    assert result.output == (
        f"Saved orca-mini-3b to {path}\n"
        "Run a prompt with: llm -m orca-mini-3b 'Hello'\n"
    )
    assert path.read_text("utf-8") == (
        "- model_id: orca-mini-3b\n"
        "  model_name: orca-mini-3b\n"
        "  api_base: http://localhost:8080\n"
    )
    # The model should now be available
    model = llm.get_model("orca-mini-3b")
    assert model.model_name == "orca-mini-3b"
    assert model.api_base == "http://localhost:8080"
    assert model.needs_key is None
    assert not model.supports_tools


def test_endpoint_add_all_options(user_path):
    (user_path / "keys.json").write_text(json.dumps({"openrouter": "sk-x"}), "utf-8")
    result = _invoke(
        "add",
        "https://openrouter.ai/api/v1",
        "-m",
        "anthropic/claude-sonnet-4.5",
        "--id",
        "claude-sonnet",
        "--alias",
        "claude",
        "--alias",
        "sonnet",
        "--key",
        "openrouter",
        "-H",
        "X-Title",
        "LLM",
        "--header",
        "HTTP-Referer",
        "https://llm.datasette.io/",
        "--responses",
        "--supports-tools",
        "--supports-schema",
        "--vision",
        "--audio",
        "--reasoning",
        "--service-tier",
        "--no-stream",
        "--api-type",
        "azure",
        "--api-version",
        "2024-02-01",
        "--api-engine",
        "engine",
    )
    assert result.exit_code == 0, result.output
    assert _read_yaml(user_path) == [
        {
            "model_id": "claude-sonnet",
            "model_name": "anthropic/claude-sonnet-4.5",
            "aliases": ["claude", "sonnet"],
            "api_base": "https://openrouter.ai/api/v1",
            "api_key_name": "openrouter",
            "headers": {"X-Title": "LLM", "HTTP-Referer": "https://llm.datasette.io/"},
            "api_type": "azure",
            "api_version": "2024-02-01",
            "api_engine": "engine",
            "responses": True,
            "supports_tools": True,
            "supports_schema": True,
            "vision": True,
            "audio": True,
            "reasoning": True,
            "service_tier": True,
            "can_stream": False,
        }
    ]
    from llm.default_plugins.openai_models import Responses

    model = llm.get_model("claude")
    assert isinstance(model, Responses)
    assert model.model_id == "claude-sonnet"
    assert model.needs_key == "openrouter"
    assert model.headers == {
        "X-Title": "LLM",
        "HTTP-Referer": "https://llm.datasette.io/",
    }
    assert model.supports_tools
    assert not model.can_stream


def test_endpoint_add_default_openai_url_omits_api_base(user_path):
    result = _invoke(
        "add", "https://api.openai.com/v1/", "-m", "gpt-5-new", "--alias", "new"
    )
    assert result.exit_code == 0, result.output
    assert _read_yaml(user_path) == [
        {"model_id": "gpt-5-new", "model_name": "gpt-5-new", "aliases": ["new"]}
    ]
    model = llm.get_model("new")
    assert model.api_base is None
    assert model.needs_key == "openai"


def test_endpoint_add_appends_preserving_existing_content(user_path):
    path = user_path / "extra-openai-models.yaml"
    path.write_text(
        "# My hand-written models\n"
        "- model_id: first\n"
        "  model_name: first-model  # trailing comment\n"
        "  api_base: http://localhost:1234",
        "utf-8",
    )
    result = _invoke("add", "http://localhost:8080", "-m", "second")
    assert result.exit_code == 0, result.output
    assert path.read_text("utf-8") == (
        "# My hand-written models\n"
        "- model_id: first\n"
        "  model_name: first-model  # trailing comment\n"
        "  api_base: http://localhost:1234\n"
        "- model_id: second\n"
        "  model_name: second\n"
        "  api_base: http://localhost:8080\n"
    )
    assert [record["model_id"] for record in _read_yaml(user_path)] == [
        "first",
        "second",
    ]


def test_endpoint_add_duplicate_requires_replace(user_path):
    assert _invoke("add", "http://localhost:8080", "-m", "orca").exit_code == 0
    assert _invoke("add", "http://localhost:8080", "-m", "other").exit_code == 0
    result = _invoke("add", "http://localhost:9999", "-m", "orca")
    assert result.exit_code == 1
    assert "A model with ID 'orca' already exists" in result.output
    assert "--replace" in result.output
    # Unchanged
    assert _read_yaml(user_path)[0]["api_base"] == "http://localhost:8080"

    result = _invoke(
        "add", "http://localhost:9999", "-m", "orca-v2", "--id", "orca", "--replace"
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Replaced orca in ")
    # Replaced in place, other record untouched
    assert _read_yaml(user_path) == [
        {
            "model_id": "orca",
            "model_name": "orca-v2",
            "api_base": "http://localhost:9999",
        },
        {
            "model_id": "other",
            "model_name": "other",
            "api_base": "http://localhost:8080",
        },
    ]


def test_endpoint_add_key_must_be_stored(user_path):
    result = _invoke("add", "http://localhost:8080", "-m", "orca", "--key", "nope")
    assert result.exit_code == 1
    assert "No stored key named 'nope' - run 'llm keys set nope' first" in result.output
    assert not (user_path / "extra-openai-models.yaml").exists()


def test_endpoint_add_responses_and_completion_conflict(user_path):
    result = _invoke(
        "add", "http://localhost:8080", "-m", "orca", "--responses", "--completion"
    )
    assert result.exit_code == 1
    assert "--responses and --completion cannot be used together" in result.output


def test_endpoint_add_rejects_non_list_file(user_path):
    path = user_path / "extra-openai-models.yaml"
    path.write_text("model_id: not-a-list\n", "utf-8")
    result = _invoke("add", "http://localhost:8080", "-m", "orca")
    assert result.exit_code == 1
    assert "should contain a YAML list of models" in result.output
    assert path.read_text("utf-8") == "model_id: not-a-list\n"


def test_endpoint_list(user_path):
    assert _invoke("list").output == ""
    assert _invoke("list", "--json").output == "[]\n"
    _invoke(
        "add",
        "http://localhost:8080",
        "-m",
        "orca-mini",
        "--id",
        "orca",
        "--alias",
        "o",
    )
    _invoke("add", "https://api.openai.com/v1", "-m", "gpt-5-new")
    result = _invoke("list")
    assert result.output == (
        "orca: orca-mini at http://localhost:8080 (aliases: o)\n"
        "gpt-5-new: gpt-5-new\n"
    )
    result = _invoke("list", "--json")
    assert json.loads(result.output) == [
        {
            "model_id": "orca",
            "model_name": "orca-mini",
            "aliases": ["o"],
            "api_base": "http://localhost:8080",
        },
        {"model_id": "gpt-5-new", "model_name": "gpt-5-new"},
    ]


def test_endpoint_remove(user_path):
    _invoke("add", "http://localhost:8080", "-m", "orca")
    _invoke("add", "http://localhost:8080", "-m", "other")
    result = _invoke("remove", "missing")
    assert result.exit_code == 1
    assert "No model with ID 'missing'" in result.output

    result = _invoke("remove", "orca")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Removed orca from ")
    assert _read_yaml(user_path) == [
        {
            "model_id": "other",
            "model_name": "other",
            "api_base": "http://localhost:8080",
        }
    ]
    with pytest.raises(llm.UnknownModelError):
        llm.get_model("orca")


def test_endpoint_add_after_removing_last_model(user_path):
    _invoke("add", "http://localhost:8080", "-m", "orca")
    _invoke("remove", "orca")
    result = _invoke("add", "http://localhost:8080", "-m", "other")
    assert result.exit_code == 0, result.output
    assert _read_yaml(user_path) == [
        {
            "model_id": "other",
            "model_name": "other",
            "api_base": "http://localhost:8080",
        }
    ]
    assert llm.get_model("other").model_name == "other"


def test_endpoint_add_to_flow_style_list(user_path):
    path = user_path / "extra-openai-models.yaml"
    path.write_text("[{model_id: first, model_name: first}]\n", "utf-8")
    result = _invoke("add", "http://localhost:8080", "-m", "second")
    assert result.exit_code == 0, result.output
    assert [record["model_id"] for record in _read_yaml(user_path)] == [
        "first",
        "second",
    ]


def test_endpoint_path(user_path):
    result = _invoke("path")
    assert result.output == f"{user_path / 'extra-openai-models.yaml'}\n"


def test_endpoint_group_help_lists_subcommands(user_path):
    result = _invoke("--help")
    assert result.exit_code == 0
    for name in ("prompt*", "add", "list", "remove", "path"):
        assert name in result.output
    # Explicit "prompt" subcommand works too
    result = _invoke("prompt", "--help")
    assert result.exit_code == 0
    assert "Usage: cli openai endpoint prompt [OPTIONS] URL [PROMPT]" in result.output
