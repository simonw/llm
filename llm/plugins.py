import importlib
from importlib import metadata
import os
import pluggy
import sys
from . import hookspecs

DEFAULT_PLUGINS = ("llm.default_plugins.openai_models",)

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

LLM_LOAD_PLUGINS = os.environ.get("LLM_LOAD_PLUGINS", None)

if not hasattr(sys, "_called_from_test") and LLM_LOAD_PLUGINS is None:
    # Only load plugins if not running tests
    pm.load_setuptools_entrypoints("llm")


# Load any plugins specified in LLM_LOAD_PLUGINS")
if LLM_LOAD_PLUGINS is not None:
    for package_name in [name for name in LLM_LOAD_PLUGINS.split(",") if name.strip()]:
        try:
            distribution = metadata.distribution(package_name)  # Updated call
            llm_entry_points = [
                ep for ep in distribution.entry_points if ep.group == "llm"
            ]
            for entry_point in llm_entry_points:
                mod = entry_point.load()
                pm.register(mod, name=entry_point.name)
                # Ensure name can be found in plugin_to_distinfo later:
                pm._plugin_distinfo.append((mod, distribution))  # type: ignore
        except metadata.PackageNotFoundError:
            sys.stderr.write(f"Plugin {package_name} could not be found\n")

for plugin in DEFAULT_PLUGINS:
    mod = importlib.import_module(plugin)
    pm.register(mod, plugin)
