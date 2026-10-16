import json

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.plugins import pm


class SingleTurnModel(llm.Model):
    model_id = "single-turn-test"
    supports_conversation = False
    can_stream = True

    def __init__(self):
        self.history = []

    def execute(self, prompt, stream, response, conversation):
        self.history.append(prompt)
        yield "hello"


class AsyncSingleTurnModel(llm.AsyncModel):
    model_id = "single-turn-test"
    supports_conversation = False
    can_stream = True

    def __init__(self):
        self.history = []

    async def execute(self, prompt, stream, response, conversation):
        self.history.append(prompt)
        yield "hello"


@pytest.fixture
def registered_single_turn_models():
    model = SingleTurnModel()
    async_model = AsyncSingleTurnModel()

    class SingleTurnPlugin:
        __name__ = "SingleTurnPlugin"

        @llm.hookimpl
        def register_models(self, register):
            register(model, async_model=async_model)

    pm.register(SingleTurnPlugin(), name="single-turn-test-plugin")
    try:
        yield
    finally:
        pm.unregister(name="single-turn-test-plugin")


def test_conversation_not_supported_is_value_error():
    assert issubclass(llm.ConversationNotSupported, ValueError)


@pytest.mark.parametrize(
    "model_class", [llm.Model, llm.KeyModel, llm.AsyncModel, llm.AsyncKeyModel]
)
def test_supports_conversation_default(model_class):
    assert model_class.supports_conversation is True


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def single_turn_model(request, registered_single_turn_models):
    get_model = llm.get_async_model if request.param else llm.get_model
    return get_model("single-turn-test")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_single_turn_prompts(single_turn_model, stream):
    model = single_turn_model
    conversation = model.conversation()
    for target in (model, model, conversation):
        response = target.prompt("Hi", system="Be helpful", stream=stream)
        text = response.text()
        if isinstance(model, llm.AsyncModel):
            text = await text
        assert text == "hello"

    with pytest.raises(
        llm.ConversationNotSupported, match="does not support conversations"
    ):
        conversation.prompt("Again", stream=stream)
    assert len(model.history) == 3
    assert len(conversation.responses) == 1


@pytest.mark.parametrize("role", ["assistant", "tool"])
@pytest.mark.parametrize("target", ["model", "conversation", "loaded_conversation"])
def test_single_turn_rejects_history(single_turn_model, role, target):
    messages = [
        llm.Message(role=role, parts=[llm.parts.TextPart(text="Previous turn")])
    ]
    model = single_turn_model
    if target == "model":
        prompt = model.prompt
    else:
        conversation = model.conversation()
        prompt = conversation.prompt
        if target == "loaded_conversation":
            conversation.loaded_messages = messages
            messages = None
    with pytest.raises(
        llm.ConversationNotSupported, match="does not support conversations"
    ):
        prompt("Hi", messages=messages)
    assert model.history == []


@pytest.mark.asyncio
async def test_single_turn_accepts_system_and_user_messages(single_turn_model):
    model = single_turn_model
    response = model.prompt(
        messages=[
            llm.Message(role="system", parts=[llm.parts.TextPart(text="Be helpful")]),
            llm.Message(role="user", parts=[llm.parts.TextPart(text="Hi")]),
        ]
    )
    text = response.text()
    if isinstance(model, llm.AsyncModel):
        text = await text
    assert text == "hello"


@pytest.mark.parametrize("continue_option", ["-c", "--cid"])
def test_single_turn_cli_continue(single_turn_model, logs_db, continue_option):
    model = single_turn_model
    runner = CliRunner()
    args = ["-m", model.model_id]
    if isinstance(model, llm.AsyncModel):
        args.append("--async")
    result = runner.invoke(cli, [*args, "Hi"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output == "hello\n"
    conversation_id = next(logs_db["threads"].rows)["id"]
    continue_args = [continue_option]
    if continue_option == "--cid":
        continue_args.append(conversation_id)
    result = runner.invoke(
        cli, [*args, *continue_args, "Again"], catch_exceptions=False
    )
    assert result.exit_code == 1
    assert result.output == f"Error: {model} does not support conversations\n"
    assert len(model.history) == 1
    assert logs_db["turns"].count == 1


def test_single_turn_cli_chat(registered_single_turn_models):
    model = llm.get_model("single-turn-test")
    result = CliRunner().invoke(
        cli, ["chat", "-m", model.model_id], input="Hi\nquit\n", catch_exceptions=False
    )
    assert result.exit_code == 1
    assert result.output == f"Error: {model} does not support conversations\n"
    assert model.history == []


@pytest.mark.parametrize(
    "model_id,supports_conversation", [("single-turn-test", False), ("mock", True)]
)
@pytest.mark.parametrize("async_", [False, True])
def test_models_json_supports_conversation(
    registered_single_turn_models, model_id, supports_conversation, async_
):
    args = ["models", "--json", "-m", model_id] + (["--async"] if async_ else [])
    result = CliRunner().invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert (
        json.loads(result.output)[0]["supports_conversation"] is supports_conversation
    )
