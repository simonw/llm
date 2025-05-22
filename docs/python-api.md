(python-api)=
# Python API

LLM provides a Python API for executing prompts, in addition to the command-line interface.

Understanding this API is also important for writing {ref}`plugins`.

## Basic prompt execution

To run a prompt against the `gpt-4o-mini` model, run this:

```python
import llm

model = llm.get_model("gpt-4o-mini")
# key= is optional, you can configure the key in other ways
response = model.prompt(
    "Five surprising names for a pet pelican",
    key="sk-..."
)
print(response.text())
```
Note that the prompt will not be evaluated until you call that `response.text()` method - a form of lazy loading.

If you inspect the response before it has been evaluated it will look like this:

    <Response prompt='Your prompt' text='... not yet done ...'>

The `llm.get_model()` function accepts model IDs or aliases. You can also omit it to use the currently configured default model, which is `gpt-4o-mini` if you have not changed the default.

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

Calling `llm.get_model()` with an invalid model ID will raise a `llm.UnknownModelError` exception.

(python-api-tools)=

### Tools

{ref}`Tools <tools>` are functions that can be executed by the model as part of a chain of responses.

You can define tools in Python code - with a docstring to describe what they do - and then pass them to the `model.prompt()` method using the `tools=` keyword argument. If the model decides to request a tool call the `response.tool_calls()` method show what the model wants to execute:

```python
import llm

def upper(text: str) -> str:
    """Convert text to uppercase."""
    return text.upper()

model = llm.get_model("gpt-4.1-mini")
response = model.prompt("Convert panda to upper", tools=[upper])
tool_calls = response.tool_calls()
# [ToolCall(name='upper', arguments={'text': 'panda'}, tool_call_id='...')]
```
You can call `response.execute_tool_calls()` to execute those calls and get back the results:
```python
tool_results = response.execute_tool_calls()
# [ToolResult(name='upper', output='PANDA', tool_call_id='...')]
```
To pass the results of the tool calls back to the model you need to use a utility method called `model.chain()`:
```python
chain_response = model.chain(
    "Convert panda to upper",
    tools=[upper],
)
print(chain_response.text())
# The word "panda" converted to uppercase is "PANDA".
```
You can also loop through the `model.chain()` response to get a stream of tokens, like this:
```python
for chunk in model.chain(
    "Convert panda to upper",
    tools=[upper],
):
    print(chunk, end="", flush=True)
```
This will stream each of the chain of responses in turn as they are generated.

You can access the individual responses that make up the chain using `chain.responses()`. This can be iterated over as the chain executes like this:

```python
chain = model.chain(
    "Convert panda to upper",
    tools=[upper],
)
for response in chain.responses():
    print(response.prompt)
    for chunk in response:
        print(chunk, end="", flush=True)
```

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

You can check which attachment types (if any) a model supports using the `model.attachment_types` set:

```python
model = llm.get_model("gpt-4o-mini")
print(model.attachment_types)
# {'image/gif', 'image/png', 'image/jpeg', 'image/webp'}

if "image/jpeg" in model.attachment_types:
    # Use a JPEG attachment here
    ...
```

(python-api-schemas)=

### Schemas

As with {ref}`the CLI tool <usage-schemas>` some models support passing a JSON schema should be used for the resulting response.

You can pass this to the `prompt(schema=)` parameter as either a Python dictionary or a [Pydantic](https://docs.pydantic.dev/) `BaseModel` subclass:

```python
import llm, json
from pydantic import BaseModel

class Dog(BaseModel):
    name: str
    age: int

model = llm.get_model("gpt-4o-mini")
response = model.prompt("Describe a nice dog", schema=Dog)
dog = json.loads(response.text())
print(dog)
# {"name":"Buddy","age":3}
```
You can also pass a schema directly, like this:
```python
response = model.prompt("Describe a nice dog", schema={
    "properties": {
        "name": {"title": "Name", "type": "string"},
        "age": {"title": "Age", "type": "integer"},
    },
    "required": ["name", "age"],
    "title": "Dog",
    "type": "object",
})
```

You can also use LLM's {ref}`alternative schema syntax <schemas-dsl>` via the `llm.schema_dsl(schema_dsl)` function. This provides a quick way to construct a JSON schema for simple cases:

```python
print(model.prompt(
    "Describe a nice dog with a surprising name",
    schema=llm.schema_dsl("name, age int, bio")
))
```
Pass `multi=True` to generate a schema that returns multiple items matching that specification:

```python
print(model.prompt(
    "Describe 3 nice dogs with surprising names",
    schema=llm.schema_dsl("name, age int, bio", multi=True)
))
```

(python-api-fragments)=

### Fragments

The {ref}`fragment system <usage-fragments>` from the CLI tool can also be accessed from the Python API, by passing `fragments=` and/or `system_fragments=` lists of strings to the `prompt()` method:

```python
response = model.prompt(
    "What do these documents say about dogs?",
    fragments=[
        open("dogs1.txt").read(),
        open("dogs2.txt").read(),
    ],
    system_fragments=[
        "You answer questions like Snoopy",
    ]
)
```
This mechanism has limited utility in Python, as you can also assemble the contents of these strings together into the `prompt=` and `system=` strings directly.

Fragments become more interesting if you are working with LLM's mechanisms for storing prompts to a SQLite database, which are not yet part of the stable, documented Python API.

Some model plugins may include features that take advantage of fragments, for example [llm-anthropic](https://github.com/simonw/llm-anthropic) aims to use them as part of a mechanism that taps into Claude's prompt caching system.


(python-api-model-options)=

### Model options

For models that support options (view those with `llm models --options`) you can pass options as keyword arguments to the `.prompt()` method:

```python
model = llm.get_model()
print(model.prompt("Names for otters", temperature=0.2))
```

(python-api-models-api-keys)=

### Passing an API key

Models that accept API keys should take an additional `key=` parameter to their `model.prompt()` method:

```python
model = llm.get_model("gpt-4o-mini")
print(model.prompt("Names for beavers", key="sk-..."))
```

If you don't provide this argument LLM will attempt to find it from an environment variable (`OPENAI_API_KEY` for OpenAI, others for different plugins) or from keys that have been saved using the {ref}`llm keys set <api-keys>` command.

Some model plugins may not yet have been upgraded to handle the `key=` parameter, in which case you will need to use one of the other mechanisms.

(python-api-models-from-plugins)=

### Models from plugins

Any models you have installed as plugins will also be available through this mechanism, for example to use Anthropic's Claude 3.5 Sonnet model with [llm-anthropic](https://github.com/simonw/llm-anthropic):

```bash
pip install llm-anthropic
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

(python-api-underlying-json)=

### Accessing the underlying JSON

Most model plugins also make a JSON version of the prompt response available. The structure of this will differ between model plugins, so building against this is likely to result in code that only works with that specific model provider.

You can access this JSON data as a Python dictionary using the `response.json()` method:

```python
import llm
from pprint import pprint

model = llm.get_model("gpt-4o-mini")
response = model.prompt("3 names for an otter")
json_data = response.json()
pprint(json_data)
```
Here's that example output from GPT-4o mini:
```python
{'content': 'Sure! Here are three fun names for an otter:\n'
            '\n'
            '1. **Splash**\n'
            '2. **Bubbles**\n'
            '3. **Otto** \n'
            '\n'
            'Feel free to mix and match or use these as inspiration!',
 'created': 1739291215,
 'finish_reason': 'stop',
 'id': 'chatcmpl-AznO31yxgBjZ4zrzBOwJvHEWgdTaf',
 'model': 'gpt-4o-mini-2024-07-18',
 'object': 'chat.completion.chunk',
 'usage': {'completion_tokens': 43,
           'completion_tokens_details': {'accepted_prediction_tokens': 0,
                                         'audio_tokens': 0,
                                         'reasoning_tokens': 0,
                                         'rejected_prediction_tokens': 0},
           'prompt_tokens': 13,
           'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0},
           'total_tokens': 56}}
```

(python-api-token-usage)=

### Token usage

Many models can return a count of the number of tokens used while executing the prompt.

The `response.usage()` method provides an abstraction over this:

```python
pprint(response.usage())
```
Example output:
```python
Usage(input=5,
      output=2,
      details={'candidatesTokensDetails': [{'modality': 'TEXT',
                                            'tokenCount': 2}],
               'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 5}]})
```
The `.input` and `.output` properties are integers representing the number of input and output tokens. The `.details` property may be a dictionary with additional custom values that vary by model.

(python-api-streaming-responses)=

### Streaming responses

For models that support it you can stream responses as they are generated, like this:

```python
response = model.prompt("Five diabolical names for a pet goat")
for chunk in response:
    print(chunk, end="")
```
The `response.text()` method described earlier does this for you - it runs through the iterator and gathers the results into a string.

If a response has been evaluated, `response.text()` will continue to return the same string.

(python-api-async)=

## Async models

Some plugins provide async versions of their supported models, suitable for use with Python [asyncio](https://docs.python.org/3/library/asyncio.html).

To use an async model, use the `llm.get_async_model()` function instead of `llm.get_model()`:

```python
import llm
model = llm.get_async_model("gpt-4o")
```
You can then run a prompt using `await model.prompt(...)`:

```python
print(await model.prompt(
    "Five surprising names for a pet pelican"
).text())
```
Or use `async for chunk in ...` to stream the response as it is generated:
```python
async for chunk in model.prompt(
    "Five surprising names for a pet pelican"
):
    print(chunk, end="", flush=True)
```
This `await model.prompt()` method takes the same arguments as the synchronous `model.prompt()` method, for options and attachments and `key=` and suchlike.

(python-api-async-tools)=

### Tool functions can be sync or async

{ref}`Tool functions <python-api-tools>` can be both synchronous or asynchronous. The latter are defined using `async def tool_name(...)`. Either kind of function can be passed to the `tools=[...]` parameter.

If an `async def` function is used in a synchronous context LLM will automatically execute it in a thread pool using `asyncio.run()`. This means the following will work even in non-asynchronous Python scripts:

```python
async def hello(name: str) -> str:
    "Say hello to name"
    return "Hello there " + name

model = llm.get_model("gpt-4.1-mini")
chain_response = model.chain(
    "Say hello to Percival", tools=[hello]
)
print(chain_response.text())
```

### Tool use for async models

Tool use is also supported for async models, using either synchronous or asynchronous tool functions. Synchronous functions will block the event loop so only use those in asynchronous context if you are certain they are extremely fast.

The `response.execute_tool_calls()` and `chain_response.text()` and `chain_response.responses()` methods must all be awaited when run against asynchronous models:

```python
import llm
model = llm.get_async_model("gpt-4.1")

def upper(string):
    "Converts string to uppercase"
    return string.upper()

chain = model.chain(
    "Convert panda to uppercase then pelican to uppercase",
    tools=[upper],
    after_call=print
)
print(await chain.text())
```

To iterate over the chained response output as it arrives use `async for`:
```python
async for chunk in model.chain(
    "Convert panda to uppercase then pelican to uppercase",
    tools=[upper]
):
    print(chunk, end="", flush=True)
```
(python-api-conversations)=

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

### Conversations using tools

You can pass a list of tool functions to the `tools=[]` argument when you start a new conversation:
```python
import llm

def upper(text: str) -> str:
    "convert text to upper case"
    return text.upper()

def reverse(text: str) -> str:
    "reverse text"
    return text[::-1]

model = llm.get_model("gpt-4.1-mini")
conversation = model.conversation(tools=[upper, reverse])
```
You can then call the `conversation.chain()` method multiple times to have a conversation that uses those tools:
```python
print(conversation.chain(
    "Convert panda to uppercase and reverse it"
).text())
print(conversation.chain(
    "Same with pangolin"
).text())
```

(python-api-listing-models)=

## Listing models

The `llm.get_models()` list returns a list of all available models, including those from plugins.

```python
import llm

for model in llm.get_models():
    print(model.model_id)
```

Use `llm.get_async_models()` to list async models:

```python
for model in llm.get_async_models():
    print(model.model_id)
```

(python-api-response-on-done)=

## Running code when a response has completed

For some applications, such as tracking the tokens used by an application, it may be useful to execute code as soon as a response has finished being executed

You can do this using the `response.on_done(callback)` method, which causes your callback function to be called as soon as the response has finished (all tokens have been returned).

The signature of the method you provide is `def callback(response)` - it can be optionally an `async def` method when working with asynchronous models.

Example usage:

```python
import llm

model = llm.get_model("gpt-4o-mini")
response = model.prompt("a poem about a hippo")
response.on_done(lambda response: print(response.usage()))
print(response.text())
```
Which outputs:
```
Usage(input=20, output=494, details={})
In a sunlit glade by a bubbling brook,
Lived a hefty hippo, with a curious look.
...
```
Or using an `asyncio` model, where you need to `await response.on_done(done)` to queue up the callback:
```python
import asyncio, llm

async def run():
    model = llm.get_async_model("gpt-4o-mini")
    response = model.prompt("a short poem about a brick")
    async def done(response):
        print(await response.usage())
        print(await response.text())
    await response.on_done(done)
    print(await response.text())

asyncio.run(run())
```

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
