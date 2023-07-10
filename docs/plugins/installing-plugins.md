# Installing plugins

Plugins must be installed in the same virtual environment as LLM itself.

You can find names of plugins to install in the [llm-plugins](https://github.com/simonw/llm-plugins) repository.

Use the `llm install` command (a thin wrapper around `pip install`) to install plugins in the correct environment:
```bash
llm install llm-hello-world
```
Plugins can be uninstalled with `llm uninstall`:
```bash
llm uninstall llm-hello-world -y
```
The `-y` flag skips asking for confirmation.

## Listing installed plugins

Run `llm plugins` to list installed plugins:

```bash
llm plugins
```
```json
[
  {
    "name": "llm-hello-world",
    "hooks": [
      "register_commands"
    ],
    "version": "0.1"
  }
]
```
You can see additional models that have been added by plugins by running:
```bash
llm models list
```
