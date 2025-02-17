(installing-plugins)=
# Installing plugins

Plugins must be installed in the same virtual environment as LLM itself.

You can find names of plugins to install in the {ref}`plugin directory <plugin-directory>`

Use the `llm install` command (a thin wrapper around `pip install`) to install plugins in the correct environment:
```bash
llm install llm-gpt4all
```
Plugins can be uninstalled with `llm uninstall`:
```bash
llm uninstall llm-gpt4all -y
```
The `-y` flag skips asking for confirmation.

You can see additional models that have been added by plugins by running:
```bash
llm models
```
Or add `--options` to include details of the options available for each model:
```bash
llm models --options
```
To run a prompt against a newly installed model, pass its name as the `-m/--model` option:
```bash
llm -m orca-mini-3b-gguf2-q4_0 'What is the capital of France?'
```

## Listing installed plugins

Run `llm plugins` to list installed plugins:

```bash
llm plugins
```
```json
[
  {
    "name": "llm-anthropic",
    "hooks": [
      "register_models"
    ],
    "version": "0.11"
  },
  {
    "name": "llm-gguf",
    "hooks": [
      "register_commands",
      "register_models"
    ],
    "version": "0.1a0"
  },
  {
    "name": "llm-clip",
    "hooks": [
      "register_commands",
      "register_embedding_models"
    ],
    "version": "0.1"
  },
  {
    "name": "llm-cmd",
    "hooks": [
      "register_commands"
    ],
    "version": "0.2a0"
  },
  {
    "name": "llm-gemini",
    "hooks": [
      "register_embedding_models",
      "register_models"
    ],
    "version": "0.3"
  }
]
```

(llm-load-plugins)=
## Running with a subset of plugins

By default, LLM will load all plugins that are installed in the same virtual environment as LLM itself.

You can control the set of plugins that is loaded using the `LLM_LOAD_PLUGINS` environment variable.

Set that to the empty string to disable all plugins:

```bash
LLM_LOAD_PLUGINS='' llm ...
```
Or to a comma-separated list of plugin names to load only those plugins:

```bash
LLM_LOAD_PLUGINS='llm-gpt4all,llm-cluster' llm ...
```
You can use the `llm plugins` command to check that it is working correctly:
```
LLM_LOAD_PLUGINS='' llm plugins
```
