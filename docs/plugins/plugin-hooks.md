(plugin-hooks)=
# Plugin hooks

Plugins use **plugin hooks** to customize LLM's behavior. These hooks are powered by the [Pluggy plugin system](https://pluggy.readthedocs.io/).

Each plugin can implement one or more hooks using the @hookimpl decorator against one of the hook function names described on this page.

LLM imitates the Datasette plugin system. The [Datasette plugin documentation](https://docs.datasette.io/en/stable/writing_plugins.html) describes how plugins work.

(plugin-hooks-register-commands)=
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

(plugin-hooks-register-models)=
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

(plugin-hooks-register-tools)=
## register_tools(register)

This hook can register one or more tool functions for use with LLM. See {ref}`the tools documentation <tools>` for more details.

This example registers two tools: `upper` and `count_character_in_word`.

```python
import llm

def upper(text: str) -> str:
    """Convert text to uppercase."""
    return text.upper()

def count_char(text: str, character: str) -> int:
    """Count the number of occurrences of a character in a word."""
    return text.count(character)

@llm.hookimpl
def register_tools(register):
    register(upper)
    # Here the name= argument is used to specify a different name for the tool:
    register(count_char, name="count_character_in_word")
```

(plugin-hooks-register-template-loaders)=
## register_template_loaders(register)

Plugins can register new {ref}`template loaders <prompt-templates-loaders>` using the `register_template_loaders` hook.

Template loaders work with the `llm -t prefix:name` syntax. The prefix specifies the loader, then the registered loader function is called with the name as an argument. The loader function should return an `llm.Template()` object.

This example plugin registers `my-prefix` as a new template loader. Once installed it can be used like this:

```bash
llm -t my-prefix:my-template
```
Here's the Python code:

```python
import llm

@llm.hookimpl
def register_template_loaders(register):
    register("my-prefix", my_template_loader)

def my_template_loader(template_path: str) -> llm.Template:
    """
    Documentation for the template loader goes here. It will be displayed
    when users run the 'llm templates loaders' command.
    """
    try:
        # Your logic to fetch the template content
        # This is just an example:
        prompt = "This is a sample prompt for {}".format(template_path)
        system = "You are an assistant specialized in {}".format(template_path)

        # Return a Template object with the required fields
        return llm.Template(
            name=template_path,
            prompt=prompt,
            system=system,
        )
    except Exception as e:
        # Raise a ValueError with a clear message if the template cannot be found
        raise ValueError(f"Template '{template_path}' could not be loaded: {str(e)}")
```
Consult the latest code in [llm/templates.py](https://github.com/simonw/llm/blob/main/llm/templates.py) for details of that `llm.Template` class.

The loader function should raise a `ValueError` if the template cannot be found or loaded correctly, providing a clear error message.

(plugin-hooks-register-fragment-loaders)=
## register_fragment_loaders(register)

Plugins can register new fragment loaders using the `register_template_loaders` hook. These can then be used with the `llm -f prefix:argument` syntax.

Fragment loader plugins differ from template loader plugins in that you can stack more than one fragment loader call together in the same prompt.

A fragment loader can return one or more string fragments or attachments, or a mixture of the two. The fragments will be concatenated together into the prompt string, while any attachments will be added to the list of attachments to be sent to the model.

The `prefix` specifies the loader. The `argument` will be passed to that registered callback..

The callback works in a very similar way to template loaders, but returns either a single `llm.Fragment`, a list of `llm.Fragment` objects, a single `llm.Attachment`, or a list that can mix `llm.Attachment` and `llm.Fragment` objects.

The `llm.Fragment` constructor takes a required string argument (the content of the fragment) and an optional second `source` argument, which is a string that may be displayed as debug information. For files this is a path and for URLs it is a URL. Your plugin can use anything you like for the `source` value.

See {ref}`the Python API documentation for attachments <python-api-attachments>` for details of the `llm.Attachment` class.

Here is some example code:

```python
import llm

@llm.hookimpl
def register_fragment_loaders(register):
    register("my-fragments", my_fragment_loader)


def my_fragment_loader(argument: str) -> llm.Fragment:
    """
    Documentation for the fragment loader goes here. It will be displayed
    when users run the 'llm fragments loaders' command.
    """
    try:
        fragment = "Fragment content for {}".format(argument)
        source = "my-fragments:{}".format(argument)
        return llm.Fragment(fragment, source)
    except Exception as ex:
        # Raise a ValueError with a clear message if the fragment cannot be loaded
        raise ValueError(
            f"Fragment 'my-fragments:{argument}' could not be loaded: {str(ex)}"
        )

# Or for the case where you want to return multiple fragments and attachments:
def my_fragment_loader(argument: str) -> list[llm.Fragment]:
    "Docs go here."
    return [
        llm.Fragment("Fragment 1 content", "my-fragments:{argument}"),
        llm.Fragment("Fragment 2 content", "my-fragments:{argument}"),
        llm.Attachment(path="/path/to/image.png"),
    ]
```
A plugin like this one can be called like so:
```bash
llm -f my-fragments:argument
```
If multiple fragments are returned they will be used as if the user passed multiple `-f X` arguments to the command.

Multiple fragments are particularly useful for things like plugins that return every file in a directory. If these were concatenated together by the plugin, a change to a single file would invalidate the de-duplicatino cache for that whole fragment. Giving each file its own fragment means we can avoid storing multiple copies of that full collection if only a single file has changed.
