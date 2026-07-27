"""
Executable model cards.

A model card is a Markdown file with YAML frontmatter that describes an LLM
model and contains enough information to register it with LLM: the plugin
that provides the model class, the class itself and the constructor
arguments needed to instantiate it.

Example card:

    ---
    model_id: anthropic/claude-opus-4-5
    plugin: llm-anthropic
    model_class: ClaudeMessages
    async_model_class: AsyncClaudeMessages
    init:
      model_id: claude-opus-4-5-20251101
      supports_pdf: true
      supports_thinking: true
      default_max_tokens: 64000
    aliases:
    - claude-opus-4.5
    ---
    # Claude Opus 4.5

    Anthropic's frontier model, released November 2025...

Cards placed in the directory returned by model_cards_dir() - usually
~/.config/io.datasette.llm/model-cards/ - are registered automatically,
via the llm.default_plugins.model_cards default plugin.
"""

import importlib
import pathlib
import re
from typing import Any, Literal, Optional, Type

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class ModelCardError(ValueError):
    pass


class ModelCard(BaseModel):
    """A parsed executable model card."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: str
    model_class: str
    plugin: Optional[str] = None
    async_model_class: Optional[str] = None
    init: dict[str, Any] = {}
    async_init: Optional[dict[str, Any]] = None
    aliases: list[str] = []
    type: Literal["chat", "embedding"] = "chat"

    def __init__(self, **data):
        super().__init__(**data)
        # Not pydantic fields, so YAML cannot set them
        self._body = ""
        self._name = None
        self._path = None

    @property
    def body(self) -> str:
        "The Markdown body of the card - the human-readable model card"
        return self._body

    @property
    def name(self) -> Optional[str]:
        return self._name

    @property
    def path(self) -> Optional[pathlib.Path]:
        return self._path

    def resolve_class(self, class_spec: str) -> Type[Any]:
        """
        Resolve a class specification to a class.

        The specification is either a fully qualified dotted path like
        "llm_anthropic.ClaudeMessages" or a bare class name like
        "ClaudeMessages", in which case the module name is derived from
        the card's plugin field ("llm-anthropic" -> "llm_anthropic").
        """
        if "." in class_spec:
            module_name, class_name = class_spec.rsplit(".", 1)
        else:
            if not self.plugin:
                raise ModelCardError(
                    f"model class '{class_spec}' is not a dotted path "
                    "so the card must specify a plugin"
                )
            module_name = self.plugin.replace("-", "_")
            class_name = class_spec
        try:
            module = importlib.import_module(module_name)
        except ImportError as ex:
            message = f"Could not import module '{module_name}': {ex}"
            if self.plugin:
                message += f" - try running: llm install {self.plugin}"
            raise ModelCardError(message)
        try:
            return getattr(module, class_name)
        except AttributeError:
            raise ModelCardError(f"Module '{module_name}' has no class '{class_name}'")

    def build_model(self):
        "Instantiate and return the model described by this card"
        cls = self.resolve_class(self.model_class)
        try:
            return cls(**self.init)
        except TypeError as ex:
            raise ModelCardError(f"Could not instantiate {self.model_class}: {ex}")

    def build_async_model(self):
        "Instantiate and return the async model, or None if there is not one"
        if not self.async_model_class:
            return None
        cls = self.resolve_class(self.async_model_class)
        init = self.async_init if self.async_init is not None else self.init
        try:
            return cls(**init)
        except TypeError as ex:
            raise ModelCardError(
                f"Could not instantiate {self.async_model_class}: {ex}"
            )


def parse_model_card(
    content: str,
    name: Optional[str] = None,
    path: Optional[pathlib.Path] = None,
) -> ModelCard:
    """
    Parse a model card from a string of Markdown with YAML frontmatter.

    Raises ModelCardError if the card is invalid.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ModelCardError(
            "Model cards must start with a '---' YAML frontmatter block"
        )
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        raise ModelCardError("Frontmatter block was never closed with '---'")
    frontmatter = "".join(lines[1:end])
    body = "".join(lines[end + 1 :]).lstrip("\n")
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as ex:
        raise ModelCardError(f"Invalid YAML in frontmatter: {ex}")
    if not isinstance(data, dict):
        raise ModelCardError("Frontmatter must be a YAML mapping")
    try:
        card = ModelCard(**data)
    except ValidationError as ex:
        raise ModelCardError(
            "Invalid model card frontmatter: "
            + "; ".join(
                "{}: {}".format(
                    ".".join(str(bit) for bit in error["loc"]) or "(root)",
                    error["msg"],
                )
                for error in ex.errors()
            )
        )
    card._body = body
    card._name = name
    card._path = path
    return card


def model_cards_dir() -> pathlib.Path:
    "Directory where user-installed model cards live"
    import llm

    return llm.user_dir() / "model-cards"


def card_filename_for_model_id(model_id: str) -> str:
    "Filesystem-safe filename for a card, derived from its model_id"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", model_id) + ".md"


def load_model_cards(
    directory: Optional[pathlib.Path] = None, on_error=None
) -> list[ModelCard]:
    """
    Load all model cards from a directory, default model_cards_dir().

    Invalid cards are skipped; on_error(path, exception) is called for each.
    """
    if directory is None:
        directory = model_cards_dir()
    cards: list[ModelCard] = []
    if not directory.is_dir():
        return cards
    for path in sorted(directory.glob("*.md")):
        try:
            cards.append(
                parse_model_card(path.read_text("utf-8"), name=path.stem, path=path)
            )
        except ModelCardError as ex:
            if on_error:
                on_error(path, ex)
    return cards


def register_model_cards(
    register, directory: Optional[pathlib.Path] = None, on_error=None
):
    """
    Register chat models from cards in a directory with LLM.

    Designed to be called from a register_models() plugin hook - plugins
    can use this to register models from a directory of cards they bundle:

        @llm.hookimpl
        def register_models(register):
            llm.model_cards.register_model_cards(
                register, pathlib.Path(__file__).parent / "cards"
            )
    """
    for card in load_model_cards(directory, on_error=on_error):
        if card.type != "chat":
            continue
        try:
            model = card.build_model()
            async_model = card.build_async_model()
        except ModelCardError as ex:
            if on_error:
                on_error(card.path, ex)
            continue
        register(model, async_model, aliases=card.aliases or None)


def register_embedding_model_cards(
    register, directory: Optional[pathlib.Path] = None, on_error=None
):
    "Register embedding models from cards in a directory with LLM"
    for card in load_model_cards(directory, on_error=on_error):
        if card.type != "embedding":
            continue
        try:
            model = card.build_model()
        except ModelCardError as ex:
            if on_error:
                on_error(card.path, ex)
            continue
        register(model, aliases=card.aliases or None)
