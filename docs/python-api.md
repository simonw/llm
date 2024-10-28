(python-api)=
# Python API

LLM provides a Python API for executing prompts, in addition to the command-line interface.

Understanding this API is also important for writing {ref}`plugins`.

## Basic prompt execution

To run a prompt against the `gpt-4o-mini` model, run this:

```python
import llm

model = llm.get_model("gpt-4o-mini")
# Optional, you can configure the key in other ways:
model.key = "sk-..."
response = model.prompt("Five surprising names for a pet pelican")
print(response.text())
```
The `llm.get_model()` function accepts model names or aliases. You can also omit it to use the currently configured default model, which is `gpt-4o-mini` if you have not changed the default.

In this example the key is set by Python code. You can also provide the key using the `OPENAI_API_KEY` environment variable, or use the `llm keys set openai` command to store it in a `keys.json` file, see {ref}`api-keys`.

The `__str__()` method of `response` also returns the text of the response, so you can do this instead:

```python
print(llm.get_model().prompt("Five surprising names for a pet pelican"))
```

You can run this command to see a list of available models and their aliases:

```bash
llm models
```
If you have set a `OPENAI_API_KEY` environment variable you can omit the `model.key = ` line.

Calling `llm.get_model()` with an invalid model name will raise a `llm.UnknownModelError` exception.

(python-api-system-prompts)=

### System prompts

For models that accept a system prompt, pass it as `system="..."`:

```python
response = model.prompt(
    "Five surprising names for a pet pelican",
    system="Answer like GlaDOS"
)
```

(python-api-attachments)=

### Attachments

Model that accept multi-modal input (images, audio, video etc) can be passed attachments using the `attachments=` keyword argument. This accepts a list of `llm.Attachment()` instances.

This example shows two attachments - one from a file path and one from a URL:
```python
import llm

model = llm.get_model("gpt-4o-mini")
response = model.prompt(
    "Describe these images",
    attachments=[
        llm.Attachment(path="pelican.jpg"),
        llm.Attachment(url="https://static.simonwillison.net/static/2024/pelicans.jpg"),
    ]
)
```
Use `llm.Attachment(content=b"binary image content here")` to pass binary content directly.

### Model options

For models that support options (view those with `llm models --options`) you can pass options as keyword arguments to the `.prompt()` method:

```python
model = llm.get_model()
print(model.prompt("Names for otters", temperature=0.2))
```

### Models from plugins

Any models you have installed as plugins will also be available through this mechanism, for example to use Anthropic's Claude 3.5 Sonnet model with [llm-claude-3](https://github.com/simonw/llm-claude-3):

```bash
pip install llm-claude-3
```
Then in your Python code:
```python
import llm

model = llm.get_model("claude-3.5-sonnet")
# Use this if you have not set the key using 'llm keys set claude':
model.key = 'YOUR_API_KEY_HERE'
response = model.prompt("Five surprising names for a pet pelican")
print(response.text())
```
Some models do not use API keys at all.

## Streaming responses

For models that support it you can stream responses as they are generated, like this:

```python
response = model.prompt("Five diabolical names for a pet goat")
for chunk in response:
    print(chunk, end="")
```
The `response.text()` method described earlier does this for you - it runs through the iterator and gathers the results into a string.

If a response has been evaluated, `response.text()` will continue to return the same string.

## Conversations

LLM supports *conversations*, where you ask follow-up questions of a model as part of an ongoing conversation.

To start a new conversation, use the `model.conversation()` method:

```python
model = llm.get_model()
conversation = model.conversation()
```
You can then use the `conversation.prompt()` method to execute prompts against this conversation:

```python
response = conversation.prompt("Five fun facts about pelicans")
print(response.text())
```
This works exactly the same as the `model.prompt()` method, except that the conversation will be maintained across multiple prompts. So if you run this next:
```python
response2 = conversation.prompt("Now do skunks")
print(response2.text())
```
You will get back five fun facts about skunks.

The `conversation.prompt()` method supports attachments as well:
```python
response = conversation.prompt(
    "Describe these birds",
    attachments=[
        llm.Attachment(url="https://static.simonwillison.net/static/2024/pelicans.jpg")
    ]
)
```

Access `conversation.responses` for a list of all of the responses that have so far been returned during the conversation.

## Other functions

The `llm` top level package includes some useful utility functions.

### set_alias(alias, model_id)

The `llm.set_alias()` function can be used to define a new alias:

```python
import llm

llm.set_alias("mini", "gpt-4o-mini")
```
The second argument can be a model identifier or another alias, in which case that alias will be resolved.

If the `aliases.json` file does not exist or contains invalid JSON it will be created or overwritten.

### remove_alias(alias)

Removes the alias with the given name from the `aliases.json` file.

Raises `KeyError` if the alias does not exist.

```python
import llm

llm.remove_alias("turbo")
```

### set_default_model(alias)

This sets the default model to the given model ID or alias. Any changes to defaults will be persisted in the LLM configuration folder, and will affect all programs using LLM on the system, including the `llm` CLI tool.

```python
import llm

llm.set_default_model("claude-3.5-sonnet")
```

### get_default_model()

This returns the currently configured default model, or `gpt-4o-mini` if no default has been set.

```python
import llm

model_id = llm.get_default_model()
```

To detect if no default has been set you can use this pattern:

```python
if llm.get_default_model(default=None) is None:
    print("No default has been set")
```
Here the `default=` parameter specifies the value that should be returned if there is no configured default.

### set_default_embedding_model(alias) and get_default_embedding_model()

These two methods work the same as `set_default_model()` and `get_default_model()` but for the default {ref}`embedding model <embeddings>` instead.