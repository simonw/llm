import sys
import types

import pytest
from click.testing import CliRunner

import llm
from llm.cli import cli
from llm.model_cards import (
    ModelCardError,
    card_filename_for_model_id,
    parse_model_card,
)


class CardDemoModel(llm.Model):
    can_stream = False

    def __init__(self, model_id="card-demo", shout=False):
        self.model_id = model_id
        self.shout = shout

    def execute(self, prompt, stream, response, conversation):
        text = prompt.prompt or ""
        yield text.upper() if self.shout else text


class AsyncCardDemoModel(llm.AsyncModel):
    can_stream = False

    def __init__(self, model_id="card-demo", shout=False):
        self.model_id = model_id
        self.shout = shout

    async def execute(self, prompt, stream, response, conversation):
        text = prompt.prompt or ""
        yield text.upper() if self.shout else text


class CardDemoEmbed(llm.EmbeddingModel):
    def __init__(self, model_id="card-demo-embed"):
        self.model_id = model_id

    def embed_batch(self, items):
        for item in items:
            yield [float(len(item)), 1.0]


@pytest.fixture
def demo_plugin_module(monkeypatch):
    module = types.ModuleType("llm_card_demo")
    module.CardDemoModel = CardDemoModel
    module.AsyncCardDemoModel = AsyncCardDemoModel
    module.CardDemoEmbed = CardDemoEmbed
    monkeypatch.setitem(sys.modules, "llm_card_demo", module)
    return module


@pytest.fixture
def cards_dir(user_path):
    path = user_path / "model-cards"
    path.mkdir()
    return path


CARD = """---
model_id: card-demo
plugin: llm-card-demo
model_class: CardDemoModel
async_model_class: AsyncCardDemoModel
init:
  model_id: card-demo
  shout: true
aliases:
- shouty
---
# Card demo

This model shouts back at you.
"""


def test_parse_model_card():
    card = parse_model_card(CARD, name="card-demo")
    assert card.model_id == "card-demo"
    assert card.plugin == "llm-card-demo"
    assert card.model_class == "CardDemoModel"
    assert card.async_model_class == "AsyncCardDemoModel"
    assert card.init == {"model_id": "card-demo", "shout": True}
    assert card.aliases == ["shouty"]
    assert card.type == "chat"
    assert card.name == "card-demo"
    assert card.body.startswith("# Card demo")
    assert "shouts back" in card.body


@pytest.mark.parametrize(
    "content,expected_error",
    (
        ("# No frontmatter here", "must start with a '---'"),
        ("---\nmodel_id: x\n", "never closed"),
        ("---\nmodel_id: [\n---\n", "Invalid YAML"),
        ("---\njust a string\n---\n", "must be a YAML mapping"),
        ("---\nmodel_id: x\n---\n", "model_class"),
        (
            "---\nmodel_id: x\nmodel_class: y\nunexpected: z\n---\n",
            "unexpected",
        ),
    ),
)
def test_parse_model_card_errors(content, expected_error):
    with pytest.raises(ModelCardError) as ex:
        parse_model_card(content)
    assert expected_error in str(ex.value)


def test_resolve_class_requires_plugin_for_bare_name():
    card = parse_model_card("---\nmodel_id: x\nmodel_class: Foo\n---\n")
    with pytest.raises(ModelCardError) as ex:
        card.build_model()
    assert "must specify a plugin" in str(ex.value)


def test_card_registers_model(demo_plugin_module, cards_dir):
    (cards_dir / "card-demo.md").write_text(CARD, "utf-8")
    model = llm.get_model("card-demo")
    assert isinstance(model, CardDemoModel)
    assert model.shout
    response = model.prompt("hello")
    assert response.text() == "HELLO"
    # Aliases should work too
    assert llm.get_model("shouty").model_id == "card-demo"
    # And the async model
    async_model = llm.get_async_model("card-demo")
    assert isinstance(async_model, AsyncCardDemoModel)


def test_card_with_dotted_class_path(demo_plugin_module, cards_dir):
    (cards_dir / "dotted.md").write_text(
        "---\n"
        "model_id: dotted-demo\n"
        "model_class: llm_card_demo.CardDemoModel\n"
        "init:\n"
        "  model_id: dotted-demo\n"
        "---\n",
        "utf-8",
    )
    model = llm.get_model("dotted-demo")
    assert isinstance(model, CardDemoModel)
    assert not model.shout


def test_embedding_card(demo_plugin_module, cards_dir):
    (cards_dir / "embed.md").write_text(
        "---\n"
        "model_id: card-demo-embed\n"
        "type: embedding\n"
        "plugin: llm-card-demo\n"
        "model_class: CardDemoEmbed\n"
        "---\n"
        "# An embedding model\n",
        "utf-8",
    )
    model = llm.get_embedding_model("card-demo-embed")
    assert isinstance(model, CardDemoEmbed)
    assert model.embed("abc") == [3.0, 1.0]


def test_broken_card_is_skipped_with_warning(demo_plugin_module, cards_dir, capsys):
    (cards_dir / "broken.md").write_text(
        "---\n"
        "model_id: broken-demo\n"
        "plugin: llm-does-not-exist\n"
        "model_class: NopeModel\n"
        "---\n",
        "utf-8",
    )
    (cards_dir / "card-demo.md").write_text(CARD, "utf-8")
    # The valid card should still register
    assert llm.get_model("card-demo").model_id == "card-demo"
    with pytest.raises(llm.UnknownModelError):
        llm.get_model("broken-demo")
    captured = capsys.readouterr()
    assert "Could not load model card" in captured.err
    assert "llm install llm-does-not-exist" in captured.err


def test_cards_cli_add_list_show_remove(demo_plugin_module, tmpdir, user_path):
    runner = CliRunner()
    card_path = tmpdir / "my-card.md"
    card_path.write_text(CARD, "utf-8")

    result = runner.invoke(cli, ["models", "cards", "add", str(card_path)])
    assert result.exit_code == 0, result.output
    assert "Installed model card" in result.output

    expected_file = user_path / "model-cards" / "card-demo.md"
    assert expected_file.exists()

    result = runner.invoke(cli, ["models", "cards", "list"])
    assert result.exit_code == 0, result.output
    assert "card-demo: card-demo (chat)" in result.output
    assert "aliases: shouty" in result.output

    result = runner.invoke(cli, ["models", "cards", "show", "card-demo"])
    assert result.exit_code == 0, result.output
    assert "This model shouts back at you." in result.output

    # Model should show up in llm models list
    result = runner.invoke(cli, ["models", "list"])
    assert result.exit_code == 0, result.output
    assert "card-demo" in result.output

    result = runner.invoke(cli, ["models", "cards", "remove", "card-demo"])
    assert result.exit_code == 0, result.output
    assert not expected_file.exists()

    result = runner.invoke(cli, ["models", "cards", "show", "card-demo"])
    assert result.exit_code != 0


def test_cards_cli_add_rejects_broken_card_without_force(tmpdir, user_path):
    runner = CliRunner()
    card_path = tmpdir / "broken.md"
    card_path.write_text(
        "---\n"
        "model_id: broken-demo\n"
        "plugin: llm-does-not-exist\n"
        "model_class: NopeModel\n"
        "---\n",
        "utf-8",
    )
    result = runner.invoke(cli, ["models", "cards", "add", str(card_path)])
    assert result.exit_code != 0
    assert "--force" in result.output

    result = runner.invoke(cli, ["models", "cards", "add", str(card_path), "--force"])
    assert result.exit_code == 0, result.output
    assert (user_path / "model-cards" / "broken-demo.md").exists()


def test_cards_cli_add_from_url(demo_plugin_module, user_path, httpx_mock):
    httpx_mock.add_response(
        url="https://example.com/cards/card-demo.md",
        text=CARD,
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["models", "cards", "add", "https://example.com/cards/card-demo.md"],
    )
    assert result.exit_code == 0, result.output
    assert (user_path / "model-cards" / "card-demo.md").exists()


def test_cards_cli_path(user_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "cards", "path"])
    assert result.exit_code == 0
    assert result.output.strip() == str(user_path / "model-cards")


def test_register_model_cards_from_explicit_directory(demo_plugin_module, tmpdir):
    # Plugins can bundle a directory of cards and register them all
    import pathlib

    from llm.model_cards import register_model_cards

    directory = pathlib.Path(str(tmpdir / "bundled-cards"))
    directory.mkdir()
    (directory / "card-demo.md").write_text(CARD, "utf-8")
    registered = []

    def register(model, async_model=None, aliases=None):
        registered.append((model, async_model, aliases))

    register_model_cards(register, directory)
    assert len(registered) == 1
    model, async_model, aliases = registered[0]
    assert isinstance(model, CardDemoModel)
    assert isinstance(async_model, AsyncCardDemoModel)
    assert aliases == ["shouty"]


def test_card_filename_for_model_id():
    assert (
        card_filename_for_model_id("anthropic/claude-opus-4-5")
        == "anthropic-claude-opus-4-5.md"
    )
    assert (
        card_filename_for_model_id("mlx-community/Llama-3.2-3B-Instruct-4bit")
        == "mlx-community-Llama-3.2-3B-Instruct-4bit.md"
    )
