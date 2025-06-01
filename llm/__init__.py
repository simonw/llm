from .hookspecs import hookimpl
from .errors import (
    ModelError,
    NeedsKeyException,
)
from .models import (
    AsyncConversation,
    AsyncKeyModel,
    AsyncModel,
    AsyncResponse,
    Attachment,
    CancelToolCall,
    Conversation,
    EmbeddingModel,
    EmbeddingModelWithAliases,
    KeyModel,
    Model,
    ModelWithAliases,
    Options,
    Prompt,
    Response,
    Tool,
    Toolbox,
    ToolCall,
    ToolOutput,
    ToolResult,
)
from .utils import schema_dsl, Fragment
from .embeddings import Collection
from .templates import Template
from .plugins import pm, load_plugins
import click
from typing import Any, Dict, List, Optional, Callable, Type, Union
import inspect
import json
import os
import pathlib
import struct

__all__ = [
    "AsyncConversation",
    "AsyncKeyModel",
    "AsyncResponse",
    "Attachment",
    "CancelToolCall",
    "Collection",
    "Conversation",
    "Fragment",
    "get_async_model",
    "get_key",
    "get_model",
    "hookimpl",
    "KeyModel",
    "Model",
    "ModelError",
    "NeedsKeyException",
    "Options",
    "Prompt",
    "Response",
    "Template",
    "Tool",
    "Toolbox",
    "ToolCall",
    "ToolOutput",
    "ToolResult",
    "user_dir",
    "schema_dsl",
]
DEFAULT_MODEL = "gpt-4o-mini"


def get_plugins(all=False):
    plugins = []
    plugin_to_distinfo = dict(pm.list_plugin_distinfo())
    for plugin in pm.get_plugins():
        if not all and plugin.__name__.startswith("llm.default_plugins."):
            continue
        plugin_info = {
            "name": plugin.__name__,
            "hooks": [h.name for h in pm.get_hookcallers(plugin)],
        }
        distinfo = plugin_to_distinfo.get(plugin)
        if distinfo:
            plugin_info["version"] = distinfo.version
            plugin_info["name"] = (
                getattr(distinfo, "name", None) or distinfo.project_name
            )
        plugins.append(plugin_info)
    return plugins


def get_models_with_aliases() -> List["ModelWithAliases"]:
    model_aliases = []

    # Include aliases from aliases.json
    aliases_path = user_dir() / "aliases.json"
    extra_model_aliases: Dict[str, list] = {}
    if aliases_path.exists():
        configured_aliases = json.loads(aliases_path.read_text())
        for alias, model_id in configured_aliases.items():
            extra_model_aliases.setdefault(model_id, []).append(alias)

    def register(model, async_model=None, aliases=None):
        alias_list = list(aliases or [])
        if model.model_id in extra_model_aliases:
            alias_list.extend(extra_model_aliases[model.model_id])
        model_aliases.append(ModelWithAliases(model, async_model, alias_list))

    load_plugins()
    pm.hook.register_models(register=register)

    return model_aliases


def _get_loaders(hook_method) -> Dict[str, Callable]:
    load_plugins()
    loaders = {}

    def register(prefix, loader):
        suffix = 0
        prefix_to_try = prefix
        while prefix_to_try in loaders:
            suffix += 1
            prefix_to_try = f"{prefix}_{suffix}"
        loaders[prefix_to_try] = loader

    hook_method(register=register)
    return loaders


def get_template_loaders() -> Dict[str, Callable[[str], Template]]:
    """Get template loaders registered by plugins."""
    return _get_loaders(pm.hook.register_template_loaders)


def get_fragment_loaders() -> Dict[
    str,
    Callable[[str], Union[Fragment, Attachment, List[Union[Fragment, Attachment]]]],
]:
    """Get fragment loaders registered by plugins."""
    return _get_loaders(pm.hook.register_fragment_loaders)


def get_tools() -> Dict[str, Union[Tool, Type[Toolbox]]]:
    """Return all tools (llm.Tool and llm.Toolbox) registered by plugins."""
    load_plugins()
    tools: Dict[str, Union[Tool, Type[Toolbox]]] = {}

    # Variable to track current plugin name
    current_plugin_name = None

    def register(
        tool_or_function: Union[Tool, Type[Toolbox], Callable[..., Any]],
        name: Optional[str] = None,
    ) -> None:
        tool: Union[Tool, Type[Toolbox], None] = None

        # If it's a Toolbox class, set the plugin field on it
        if inspect.isclass(tool_or_function):
            if issubclass(tool_or_function, Toolbox):
                tool = tool_or_function
                if current_plugin_name:
                    tool.plugin = current_plugin_name
                tool.name = name or tool.__name__
            else:
                raise TypeError(
                    "Toolbox classes must inherit from llm.Toolbox, {} does not.".format(
                        tool_or_function.__name__
                    )
                )

        # If it's already a Tool instance, use it directly
        elif isinstance(tool_or_function, Tool):
            tool = tool_or_function
            if name:
                tool.name = name
            if current_plugin_name:
                tool.plugin = current_plugin_name

        # If it's a bare function, wrap it in a Tool
        else:
            tool = Tool.function(tool_or_function, name=name)
            if current_plugin_name:
                tool.plugin = current_plugin_name

        # Get the name for the tool/toolbox
        if tool:
            # For Toolbox classes, use their name attribute or class name
            if inspect.isclass(tool) and issubclass(tool, Toolbox):
                prefix = name or getattr(tool, "name", tool.__name__) or ""
            else:
                prefix = name or tool.name or ""

            suffix = 0
            candidate = prefix

            # Avoid name collisions
            while candidate in tools:
                suffix += 1
                candidate = f"{prefix}_{suffix}"

            tools[candidate] = tool

    # Call each plugin's register_tools hook individually to track current_plugin_name
    for plugin in pm.get_plugins():
        current_plugin_name = pm.get_name(plugin)
        hook_caller = pm.hook.register_tools
        plugin_impls = [
            impl for impl in hook_caller.get_hookimpls() if impl.plugin is plugin
        ]
        for impl in plugin_impls:
            impl.function(register=register)

    return tools


def get_embedding_models_with_aliases() -> List["EmbeddingModelWithAliases"]:
    model_aliases = []

    # Include aliases from aliases.json
    aliases_path = user_dir() / "aliases.json"
    extra_model_aliases: Dict[str, list] = {}
    if aliases_path.exists():
        configured_aliases = json.loads(aliases_path.read_text())
        for alias, model_id in configured_aliases.items():
            extra_model_aliases.setdefault(model_id, []).append(alias)

    def register(model, aliases=None):
        alias_list = list(aliases or [])
        if model.model_id in extra_model_aliases:
            alias_list.extend(extra_model_aliases[model.model_id])
        model_aliases.append(EmbeddingModelWithAliases(model, alias_list))

    load_plugins()
    pm.hook.register_embedding_models(register=register)

    return model_aliases


def get_embedding_models():
    models = []

    def register(model, aliases=None):
        models.append(model)

    load_plugins()
    pm.hook.register_embedding_models(register=register)
    return models


def get_embedding_model(name):
    aliases = get_embedding_model_aliases()
    try:
        return aliases[name]
    except KeyError:
        raise UnknownModelError("Unknown model: " + str(name))


def get_embedding_model_aliases() -> Dict[str, EmbeddingModel]:
    model_aliases = {}
    for model_with_aliases in get_embedding_models_with_aliases():
        for alias in model_with_aliases.aliases:
            model_aliases[alias] = model_with_aliases.model
        model_aliases[model_with_aliases.model.model_id] = model_with_aliases.model
    return model_aliases


def get_async_model_aliases() -> Dict[str, AsyncModel]:
    async_model_aliases = {}
    for model_with_aliases in get_models_with_aliases():
        if model_with_aliases.async_model:
            for alias in model_with_aliases.aliases:
                async_model_aliases[alias] = model_with_aliases.async_model
            async_model_aliases[model_with_aliases.model.model_id] = (
                model_with_aliases.async_model
            )
    return async_model_aliases


def get_model_aliases() -> Dict[str, Model]:
    model_aliases = {}
    for model_with_aliases in get_models_with_aliases():
        if model_with_aliases.model:
            for alias in model_with_aliases.aliases:
                model_aliases[alias] = model_with_aliases.model
            model_aliases[model_with_aliases.model.model_id] = model_with_aliases.model
    return model_aliases


class UnknownModelError(KeyError):
    pass


def get_models() -> List[Model]:
    "Get all registered models"
    models_with_aliases = get_models_with_aliases()
    return [mwa.model for mwa in models_with_aliases if mwa.model]


def get_async_models() -> List[AsyncModel]:
    "Get all registered async models"
    models_with_aliases = get_models_with_aliases()
    return [mwa.async_model for mwa in models_with_aliases if mwa.async_model]


def get_async_model(name: Optional[str] = None) -> AsyncModel:
    "Get an async model by name or alias"
    aliases = get_async_model_aliases()
    name = name or get_default_model()
    try:
        return aliases[name]
    except KeyError:
        # Does a sync model exist?
        sync_model = None
        try:
            sync_model = get_model(name, _skip_async=True)
        except UnknownModelError:
            pass
        if sync_model:
            raise UnknownModelError("Unknown async model (sync model exists): " + name)
        else:
            raise UnknownModelError("Unknown model: " + name)


def get_model(name: Optional[str] = None, _skip_async: bool = False) -> Model:
    "Get a model by name or alias"
    aliases = get_model_aliases()
    name = name or get_default_model()
    try:
        return aliases[name]
    except KeyError:
        # Does an async model exist?
        if _skip_async:
            raise UnknownModelError("Unknown model: " + name)
        async_model = None
        try:
            async_model = get_async_model(name)
        except UnknownModelError:
            pass
        if async_model:
            raise UnknownModelError("Unknown model (async model exists): " + name)
        else:
            raise UnknownModelError("Unknown model: " + name)


def get_key(
    explicit_key: Optional[str] = None,
    key_alias: Optional[str] = None,
    env_var: Optional[str] = None,
    *,
    alias: Optional[str] = None,
    env: Optional[str] = None,
    input: Optional[str] = None,
) -> Optional[str]:
    """
    Return an API key based on a hierarchy of potential sources. You should use the keyword arguments,
    the positional arguments are here purely for backwards-compatibility with older code.

    :param input: Input provided by the user. This may be the key, or an alias of a key in keys.json.
    :param alias: The alias used to retrieve the key from the keys.json file.
    :param env: Name of the environment variable to check for the key as a final fallback.
    """
    if alias:
        key_alias = alias
    if env:
        env_var = env
    if input:
        explicit_key = input
    stored_keys = load_keys()
    # If user specified an alias, use the key stored for that alias
    if explicit_key in stored_keys:
        return stored_keys[explicit_key]
    if explicit_key:
        # User specified a key that's not an alias, use that
        return explicit_key
    # Stored key over-rides environment variables over-ride the default key
    if key_alias in stored_keys:
        return stored_keys[key_alias]
    # Finally try environment variable
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    # Couldn't find it
    return None


def load_keys():
    path = user_dir() / "keys.json"
    if path.exists():
        return json.loads(path.read_text())
    else:
        return {}


def user_dir():
    llm_user_path = os.environ.get("LLM_USER_PATH")
    if llm_user_path:
        path = pathlib.Path(llm_user_path)
    else:
        path = pathlib.Path(click.get_app_dir("io.datasette.llm"))
    path.mkdir(exist_ok=True, parents=True)
    return path


def set_alias(alias, model_id_or_alias):
    """
    Set an alias to point to the specified model.
    """
    path = user_dir() / "aliases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}\n")
    try:
        current = json.loads(path.read_text())
    except json.decoder.JSONDecodeError:
        # We're going to write a valid JSON file in a moment:
        current = {}
    # Resolve model_id_or_alias to a model_id
    try:
        model = get_model(model_id_or_alias)
        model_id = model.model_id
    except UnknownModelError:
        # Try to resolve it to an embedding model
        try:
            model = get_embedding_model(model_id_or_alias)
            model_id = model.model_id
        except UnknownModelError:
            # Set the alias to the exact string they provided instead
            model_id = model_id_or_alias
    current[alias] = model_id
    path.write_text(json.dumps(current, indent=4) + "\n")


def remove_alias(alias):
    """
    Remove an alias.
    """
    path = user_dir() / "aliases.json"
    if not path.exists():
        raise KeyError("No aliases.json file exists")
    try:
        current = json.loads(path.read_text())
    except json.decoder.JSONDecodeError:
        raise KeyError("aliases.json file is not valid JSON")
    if alias not in current:
        raise KeyError("No such alias: {}".format(alias))
    del current[alias]
    path.write_text(json.dumps(current, indent=4) + "\n")


def encode(values):
    return struct.pack("<" + "f" * len(values), *values)


def decode(binary):
    return struct.unpack("<" + "f" * (len(binary) // 4), binary)


def cosine_similarity(a, b):
    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sum(x * x for x in a) ** 0.5
    magnitude_b = sum(x * x for x in b) ** 0.5
    return dot_product / (magnitude_a * magnitude_b)


def get_default_model(filename="default_model.txt", default=DEFAULT_MODEL):
    path = user_dir() / filename
    if path.exists():
        return path.read_text().strip()
    else:
        return default


def set_default_model(model, filename="default_model.txt"):
    path = user_dir() / filename
    if model is None and path.exists():
        path.unlink()
    else:
        path.write_text(model)


def get_default_embedding_model():
    return get_default_model("default_embedding_model.txt", None)


def set_default_embedding_model(model):
    set_default_model(model, "default_embedding_model.txt")
