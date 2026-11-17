"""
A model configured with a custom ``api_base`` must never send the user's
OpenAI API key - stored as ``openai`` or set as ``OPENAI_API_KEY`` - to that
third-party endpoint.
"""

import json

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli

CUSTOM_BASE = "http://custom.localhost/v1"
STORED_OPENAI_KEY = "sk-stored-openai-key-must-not-leak"
ENV_OPENAI_KEY = "sk-env-openai-key-must-not-leak"
OPENAI_KEYS = (STORED_OPENAI_KEY, ENV_OPENAI_KEY)
CUSTOM_KEY = "custom-endpoint-key"
NO_KEY_MESSAGE = "No key found - add one using 'llm keys set custom'"

EXTRA_MODELS_YAML = f"""
- model_id: custom-chat
  model_name: remote-model
  api_base: {CUSTOM_BASE}
- model_id: custom-chat-named-key
  model_name: remote-model
  api_base: {CUSTOM_BASE}
  api_key_name: custom
- model_id: custom-completion
  model_name: remote-model
  api_base: {CUSTOM_BASE}
  completion: true
- model_id: custom-completion-named-key
  model_name: remote-model
  api_base: {CUSTOM_BASE}
  api_key_name: custom
  completion: true
- model_id: custom-responses
  model_name: remote-model
  api_base: {CUSTOM_BASE}
  responses: true
- model_id: custom-responses-named-key
  model_name: remote-model
  api_base: {CUSTOM_BASE}
  api_key_name: custom
  responses: true
"""

CHAT_PAYLOAD = {
    "id": "chatcmpl_test",
    "object": "chat.completion",
    "created": 1,
    "model": "remote-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from custom"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 3, "total_tokens": 4},
}

COMPLETION_PAYLOAD = {
    "id": "cmpl_test",
    "object": "text_completion",
    "created": 1,
    "model": "remote-model",
    "choices": [{"index": 0, "text": "Hello from custom", "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 3, "total_tokens": 4},
}

RESPONSES_PAYLOAD = {
    "id": "resp_test",
    "object": "response",
    "created_at": 1,
    "model": "remote-model",
    "output": [
        {
            "type": "message",
            "id": "msg_test",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": "Hello from custom", "annotations": []}
            ],
        }
    ],
    "usage": {"input_tokens": 1, "output_tokens": 3, "total_tokens": 4},
    "status": "completed",
}

# kind -> (base model_id, extra prompt options, endpoint path hit)
KINDS = {
    "chat": ("custom-chat", {}, "/v1/chat/completions"),
    "completion": ("custom-completion", {}, "/v1/completions"),
    "responses": ("custom-responses", {}, "/v1/responses"),
    "responses-chat-completions": (
        "custom-responses",
        {"chat_completions": True},
        "/v1/chat/completions",
    ),
}
SYNC_KINDS = list(KINDS)
# Completion models have no async variant
ASYNC_KINDS = [kind for kind in KINDS if kind != "completion"]

# none: no api_key_name configured
# stored: api_key_name configured and that key has been stored
# missing: api_key_name configured but that key is not stored
KEY_STATES = ("none", "stored", "missing")

# Where the user's OpenAI key lives
OPENAI_SOURCES = ("stored", "env", "both")


@pytest.fixture
def custom_endpoint(httpx2_mock, user_path):
    (user_path / "extra-openai-models.yaml").write_text(EXTRA_MODELS_YAML, "utf-8")
    for path, payload in (
        ("chat/completions", CHAT_PAYLOAD),
        ("completions", COMPLETION_PAYLOAD),
        ("responses", RESPONSES_PAYLOAD),
    ):
        httpx2_mock.add_response(
            method="POST",
            url=f"{CUSTOM_BASE}/{path}",
            json=payload,
            headers={"Content-Type": "application/json"},
            is_optional=True,
            is_reusable=True,
        )
    return httpx2_mock


def setup_keys(user_path, monkeypatch, openai_source, key_state):
    keys = {}
    if openai_source in ("stored", "both"):
        keys["openai"] = STORED_OPENAI_KEY
    if key_state == "stored":
        keys["custom"] = CUSTOM_KEY
    (user_path / "keys.json").write_text(json.dumps(keys), "utf-8")
    if openai_source in ("env", "both"):
        monkeypatch.setenv("OPENAI_API_KEY", ENV_OPENAI_KEY)
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def model_id_for(kind, key_state):
    model_id = KINDS[kind][0]
    if key_state != "none":
        model_id += "-named-key"
    return model_id


def assert_no_openai_key(httpx2_mock):
    for request in httpx2_mock.get_requests():
        for name, value in request.headers.items():
            for secret in OPENAI_KEYS:
                assert secret not in value, f"OpenAI key leaked in {name} header"
        body = request.content.decode("utf-8")
        for secret in OPENAI_KEYS:
            assert secret not in body, "OpenAI key leaked in request body"


def assert_sent_with(httpx2_mock, kind, key_state):
    requests = httpx2_mock.get_requests()
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url).startswith(CUSTOM_BASE)
    assert request.url.path == KINDS[kind][2]
    expected = CUSTOM_KEY if key_state == "stored" else "DUMMY_KEY"
    assert request.headers["Authorization"] == f"Bearer {expected}"


@pytest.mark.parametrize("openai_source", OPENAI_SOURCES)
@pytest.mark.parametrize("key_state", KEY_STATES)
@pytest.mark.parametrize("kind", SYNC_KINDS)
def test_custom_api_base_never_receives_openai_key(
    custom_endpoint, user_path, monkeypatch, kind, key_state, openai_source
):
    setup_keys(user_path, monkeypatch, openai_source, key_state)
    model = llm.get_model(model_id_for(kind, key_state))
    options = KINDS[kind][1]
    if key_state == "missing":
        with pytest.raises(llm.NeedsKeyException) as ex:
            model.prompt("hi", stream=False, **options).text()
        assert str(ex.value) == NO_KEY_MESSAGE
        assert custom_endpoint.get_requests() == []
    else:
        assert model.prompt("hi", stream=False, **options).text() == (
            "Hello from custom"
        )
        assert_sent_with(custom_endpoint, kind, key_state)
    assert_no_openai_key(custom_endpoint)


@pytest.mark.asyncio
@pytest.mark.parametrize("openai_source", OPENAI_SOURCES)
@pytest.mark.parametrize("key_state", KEY_STATES)
@pytest.mark.parametrize("kind", ASYNC_KINDS)
async def test_async_custom_api_base_never_receives_openai_key(
    custom_endpoint, user_path, monkeypatch, kind, key_state, openai_source
):
    setup_keys(user_path, monkeypatch, openai_source, key_state)
    model = llm.get_async_model(model_id_for(kind, key_state))
    options = KINDS[kind][1]
    if key_state == "missing":
        with pytest.raises(llm.NeedsKeyException) as ex:
            await model.prompt("hi", stream=False, **options).text()
        assert str(ex.value) == NO_KEY_MESSAGE
        assert custom_endpoint.get_requests() == []
    else:
        text = await model.prompt("hi", stream=False, **options).text()
        assert text == "Hello from custom"
        assert_sent_with(custom_endpoint, kind, key_state)
    assert_no_openai_key(custom_endpoint)


@pytest.mark.parametrize("model_id", ("custom-chat", "custom-responses"))
def test_custom_api_base_models_have_no_key_env_var(custom_endpoint, model_id):
    for model in (llm.get_model(model_id), llm.get_async_model(model_id)):
        assert model.needs_key is None
        assert model.key_env_var is None


@pytest.mark.parametrize(
    "model_id", ("custom-chat-named-key", "custom-responses-named-key")
)
def test_named_key_models_have_no_key_env_var(custom_endpoint, model_id):
    for model in (llm.get_model(model_id), llm.get_async_model(model_id)):
        assert model.needs_key == "custom"
        assert model.key_env_var is None


@pytest.mark.parametrize(
    "args",
    (
        ["-m", "custom-chat-named-key"],
        ["-m", "custom-responses-named-key"],
        ["-m", "custom-responses-named-key", "-o", "chat_completions", "1"],
    ),
)
def test_cli_missing_named_key_errors(custom_endpoint, user_path, monkeypatch, args):
    setup_keys(user_path, monkeypatch, "both", "missing")
    result = CliRunner().invoke(cli, ["hi", "--no-stream"] + args)
    # Under pytest the CLI re-raises instead of showing "Error: ..."
    assert result.exit_code == 1
    assert isinstance(result.exception, llm.NeedsKeyException)
    assert str(result.exception) == NO_KEY_MESSAGE
    assert custom_endpoint.get_requests() == []


@pytest.mark.parametrize("args", ([], ["-o", "chat_completions", "1"]))
def test_cli_responses_model_does_not_leak_openai_key(
    custom_endpoint, user_path, monkeypatch, args
):
    setup_keys(user_path, monkeypatch, "both", "none")
    result = CliRunner().invoke(
        cli,
        ["hi", "--no-stream", "-m", "custom-responses"] + args,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == "Hello from custom\n"
    kind = "responses-chat-completions" if args else "responses"
    assert_sent_with(custom_endpoint, kind, "none")
    assert_no_openai_key(custom_endpoint)


def test_openai_endpoint_command_responses_chat_completions_no_leak(
    custom_endpoint, user_path, monkeypatch
):
    # llm openai endpoint URL --responses -o chat_completions 1 without --key
    # takes the same Responses -> Chat delegate path
    setup_keys(user_path, monkeypatch, "both", "none")
    result = CliRunner().invoke(
        cli,
        [
            "openai",
            "endpoint",
            CUSTOM_BASE,
            "hi",
            "-m",
            "remote-model",
            "--responses",
            "--no-stream",
            "-o",
            "chat_completions",
            "1",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert result.output == "Hello from custom\n"
    assert_sent_with(custom_endpoint, "responses-chat-completions", "none")
    assert_no_openai_key(custom_endpoint)
