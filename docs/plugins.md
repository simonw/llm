# Plugins

LLM plugins can provide extra features to the tool.

The [llm-hello-world](https://github.com/simonw/llm-hello-world) plugin is the current best example of how to build and package a plugin.

## Installing plugins

Plugins must be installed in the same virtual environment as LLM itself. You can use the `llm install` command (a thin wrapper around `pip install`) for this:
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

## Plugin hooks

Plugins use **plugin hooks** to customize LLM's behavior. These hooks are powered by the [Pluggy plugin system](https://pluggy.readthedocs.io/).

Each plugin can implement one or more hooks using the @hookimpl decorator against one of the hook function names described on this page.

LLM imitates the Datasette plugin system. The [Datasette plugin documentation](https://docs.datasette.io/en/stable/writing_plugins.html) describes how plugins work.

### register_commands(cli)

This hook adds new commands to the `llm` CLI tool - for example `llm extra-command`.

This example plugin adds a new `hello-world` command that prints "Hello world!":

```python
from llm import hookimpl
import click

@hookimpl
def register_commands(cli):
    @cli.command(name="hello-world")
    def hello_world():
        "Print hello world"
        click.echo("Hello world!")
```
This new command will be added to `llm --help` and can be run using `llm hello-world`.