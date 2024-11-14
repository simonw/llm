# Plugin hooks

Plugins use **plugin hooks** to customize LLM's behavior. These hooks are powered by the [Pluggy plugin system](https://pluggy.readthedocs.io/).

Each plugin can implement one or more hooks using the @hookimpl decorator against one of the hook function names described on this page.

LLM imitates the Datasette plugin system. The [Datasette plugin documentation](https://docs.datasette.io/en/stable/writing_plugins.html) describes how plugins work.

## register_commands(cli)

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

## register_models(register)

This hook can be used to register one or more additional models.

```python
import llm

@llm.hookimpl
def register_models(register):
    register(HelloWorld())

class HelloWorld(llm.Model):
    model_id = "helloworld"

    def execute(self, prompt, stream, response):
        return ["hello world"]
```
If your model includes an async version, you can register that too:

```python
class AsyncHelloWorld(llm.AsyncModel):
    model_id = "helloworld"

    async def execute(self, prompt, stream, response):
        return ["hello world"]

@llm.hookimpl
def register_models(register):
    register(HelloWorld(), AsyncHelloWorld(), aliases=("hw",))
```
This demonstrates how to register a model with both sync and async versions, and how to specify an alias for that model.

The {ref}`model plugin tutorial <tutorial-model-plugin>` describes how to use this hook in detail. Asynchronous models {ref}`are described here <advanced-model-plugins-async>`.

