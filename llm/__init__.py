from .hookspecs import hookimpl
from .errors import (
    ModelError,
    NeedsKeyException,
)
from .models import (
    Conversation,
    Model,
    ModelWithAliases,
    Options,
    Prompt,
    Response,
)
from .templates import Template
from .plugins import pm
import click
from typing import Dict, List, Optional
import json
import os
import pathlib

__all__ = [
    "hookimpl",
    "get_model",
    "get_key",
    "user_dir",
    "Conversation",
    "Model",
    "Options",
    "Prompt",
    "Response",
    "Template",
    "ModelError",
    "NeedsKeyException",
]


def get_plugins():
    plugins = []
    plugin_to_distinfo = dict(pm.list_plugin_distinfo())
    for plugin in pm.get_plugins():
        plugin_info = {
            "name": plugin.__name__,
            "hooks": [h.name for h in pm.get_hookcallers(plugin)],
        }
        distinfo = plugin_to_distinfo.get(plugin)
        if distinfo:
            plugin_info["version"] = distinfo.version
            plugin_info["name"] = distinfo.project_name
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

    def register(model, aliases=None):
        alias_list = list(aliases or [])
        if model.model_id in extra_model_aliases:
            alias_list.extend(extra_model_aliases[model.model_id])
        model_aliases.append(ModelWithAliases(model, alias_list))

    pm.hook.register_models(register=register)

    return model_aliases


def get_model_aliases() -> Dict[str, Model]:
    model_aliases = {}
    for model_with_aliases in get_models_with_aliases():
        for alias in model_with_aliases.aliases:
            model_aliases[alias] = model_with_aliases.model
        model_aliases[model_with_aliases.model.model_id] = model_with_aliases.model
    return model_aliases


class UnknownModelError(KeyError):
    pass


def get_model(name):
    aliases = get_model_aliases()
    try:
        return aliases[name]
    except KeyError:
        raise UnknownModelError("Unknown model: " + name)


def get_key(
    explicit_key: Optional[str], key_alias: str, env_var: Optional[str] = None
) -> Optional[str]:
    """
    Return an API key based on a hierarchy of potential sources.

    :param provided_key: A key provided by the user. This may be the key, or an alias of a key in keys.json.
    :param key_alias: The alias used to retrieve the key from the keys.json file.
    :param env_var: Name of the environment variable to check for the key.
    """
    stored_keys = load_keys()
    # If user specified an alias, use the key stored for that alias
    if explicit_key in stored_keys:
        return stored_keys[explicit_key]
    if explicit_key:
        # User specified a key that's not an alias, use that
        return explicit_key
    # Environment variables over-ride the default key
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    # Return the key stored for the default alias
    return stored_keys.get(key_alias)


def load_keys():
    path = user_dir() / "keys.json"
    if path.exists():
        return json.loads(path.read_text())
    else:
        return {}


def user_dir():
    llm_user_path = os.environ.get("LLM_USER_PATH")
    if llm_user_path:
        return pathlib.Path(llm_user_path)
    return pathlib.Path(click.get_app_dir("io.datasette.llm"))


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
        # Set the alias to the exact string they provided instead
        model_id = model_id_or_alias
    current[alias] = model_id
    path.write_text(json.dumps(current, indent=4) + "\n")
