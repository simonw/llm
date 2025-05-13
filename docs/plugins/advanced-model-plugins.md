(advanced-model-plugins)=
# Advanced model plugins

The {ref}`model plugin tutorial <tutorial-model-plugin>` covers the basics of developing a plugin that adds support for a new model. This document covers more advanced topics.

Features to consider for your model plugin include:

- {ref}`Accepting API keys <advanced-model-plugins-api-keys>` using the standard mechanism that incorporates `llm keys set`, environment variables and support for passing an explicit key to the model.
- Including support for {ref}`Async models <advanced-model-plugins-async>` that can be used with Python's `asyncio` library.
- Support for {ref}`structured output <advanced-model-plugins-schemas>` using JSON schemas.
- Handling {ref}`attachments <advanced-model-plugins-attachments>` (images, audio and more) for multi-modal models.
- Tracking {ref}`token usage <advanced-model-plugins-usage>` for models that charge by the token.

(advanced-model-plugins-lazy)=

## Tip: lazily load expensive dependencies

If your plugin depends on an expensive library such as [PyTorch](https://pytorch.org/) you should avoid importing that dependency (or a dependency that uses that dependency) at the top level of your module. Expensive imports in plugins mean that even simple commands like `llm --help` can take a long time to run.

Instead, move those imports to inside the methods that need them. Here's an example [change to llm-sentence-transformers](https://github.com/simonw/llm-sentence-transformers/commit/f87df71e8a652a8cb05ad3836a79b815bcbfa64b) that shaved 1.8 seconds off the time it took to run `llm --help`!

(advanced-model-plugins-api-keys)=

## Models that accept API keys

Models that call out to API providers such as OpenAI, Anthropic or Google Gemini usually require an API key.

LLM's API key management mechanism {ref}`is described here <api-keys>`.

If your plugin requires an API key you should subclass the `llm.KeyModel` class instead of the `llm.Model` class. Start your model definition like this:

```python
import llm

class HostedModel(llm.KeyModel):
    needs_key = "hosted" # Required
    key_env_var = "HOSTED_API_KEY" # Optional
```
This tells LLM that your model requires an API key, which may be saved in the key registry under the key name `hosted` or might also be provided as the `HOSTED_API_KEY` environment variable.

Then when you define your `execute()` method it should take an extra `key=` parameter like this:

```python
    def execute(self, prompt, stream, response, conversation, key=None):
        # key= here will be the API key to use
```
LLM will pass in the key from the environment variable, key registry or that has been passed to LLM as the `--key` command-line option or the `model.prompt(..., key=)` parameter.

(advanced-model-plugins-async)=

## Async models

Plugins can optionally provide an asynchronous version of their model, suitable for use with Python [asyncio](https://docs.python.org/3/library/asyncio.html). This is particularly useful for remote models accessible by an HTTP API.

The async version of a model subclasses `llm.AsyncModel` instead of `llm.Model`. It must implement an `async def execute()` async generator method instead of `def execute()`.

This example shows a subset of the OpenAI default plugin illustrating how this method might work:

```python
from typing import AsyncGenerator
import llm

class MyAsyncModel(llm.AsyncModel):
    # This can duplicate the model_id of the sync model:
    model_id = "my-model-id"

    async def execute(
        self, prompt, stream, response, conversation=None
    ) -> AsyncGenerator[str, None]:
        if stream:
            completion = await client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                stream=True,
            )
            async for chunk in completion:
                yield chunk.choices[0].delta.content
        else:
            completion = await client.chat.completions.create(
                model=self.model_name or self.model_id,
                messages=messages,
                stream=False,
            )
            if completion.choices[0].message.content is not None:
                yield completion.choices[0].message.content
```
If your model takes an API key you should instead subclass `llm.AsyncKeyModel` and have a `key=` parameter on your `.execute()` method:

```python
class MyAsyncModel(llm.AsyncKeyModel):
    ...
    async def execute(
        self, prompt, stream, response, conversation=None, key=None
    ) -> AsyncGenerator[str, None]:
```


This async model instance should then be passed to the `register()` method in the `register_models()` plugin hook:

```python
@hookimpl
def register_models(register):
    register(
        MyModel(), MyAsyncModel(), aliases=("my-model-aliases",)
    )
```

(advanced-model-plugins-schemas)=

## Supporting schemas

If your model supports {ref}`structured output <schemas>` against a defined JSON schema you can implement support by first adding `supports_schema = True` to the class:

```python
class MyModel(llm.KeyModel):
    ...
    support_schema = True
```
And then adding code to your `.execute()` method that checks for `prompt.schema` and, if it is present, uses that to prompt the model.

`prompt.schema` will always be a Python dictionary representing a JSON schema, even if the user passed in a Pydantic model class.

Check the [llm-gemini](https://github.com/simonw/llm-gemini) and [llm-anthropic](https://github.com/simonw/llm-anthropic) plugins for example of this pattern in action.

(advanced-model-plugins-attachments)=

## Attachments for multi-modal models

Models such as GPT-4o, Claude 3.5 Sonnet and Google's Gemini 1.5 are multi-modal: they accept input in the form of images and maybe even audio, video and other formats.

LLM calls these **attachments**. Models can specify the types of attachments they accept and then implement special code in the `.execute()` method to handle them.

See {ref}`the Python attachments documentation <python-api-attachments>` for details on using attachments in the Python API.

### Specifying attachment types

A `Model` subclass can list the types of attachments it accepts by defining a `attachment_types` class attribute:

```python
class NewModel(llm.Model):
    model_id = "new-model"
    attachment_types = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
```
These content types are detected when an attachment is passed to LLM using `llm -a filename`, or can be specified by the user using the `--attachment-type filename image/png` option.

**Note:** MP3 files will have their attachment type detected as `audio/mpeg`, not `audio/mp3`.

LLM will use the `attachment_types` attribute to validate that provided attachments should be accepted before passing them to the model.

### Handling attachments

The `prompt` object passed to the `execute()` method will have an `attachments` attribute containing a list of `Attachment` objects provided by the user.

An `Attachment` instance has the following properties:

- `url (str)`: The URL of the attachment, if it was provided as a URL
- `path (str)`: The resolved file path of the attachment, if it was provided as a file
- `type (str)`: The content type of the attachment, if it was provided
- `content (bytes)`: The binary content of the attachment, if it was provided

Generally only one of `url`, `path` or `content` will be set.

You should usually access the type and the content through one of these methods:

- `attachment.resolve_type() -> str`: Returns the `type` if it is available, otherwise attempts to guess the type by looking at the first few bytes of content
- `attachment.content_bytes() -> bytes`: Returns the binary content, which it may need to read from a file or fetch from a URL
- `attachment.base64_content() -> str`: Returns that content as a base64-encoded string

A `id()` method returns a database ID for this content, which is either a SHA256 hash of the binary content or, in the case of attachments hosted at an external URL, a hash of `{"url": url}` instead. This is an implementation detail which you should not need to access directly.

Note that it's possible for a prompt with an attachments to not include a text prompt at all, in which case `prompt.prompt` will be `None`.

Here's how the OpenAI plugin handles attachments, including the case where no `prompt.prompt` was provided:

```python
if not prompt.attachments:
    messages.append({"role": "user", "content": prompt.prompt})
else:
    attachment_message = []
    if prompt.prompt:
        attachment_message.append({"type": "text", "text": prompt.prompt})
    for attachment in prompt.attachments:
        attachment_message.append(_attachment(attachment))
    messages.append({"role": "user", "content": attachment_message})


# And the code for creating the attachment message
def _attachment(attachment):
    url = attachment.url
    base64_content = ""
    if not url or attachment.resolve_type().startswith("audio/"):
        base64_content = attachment.base64_content()
        url = f"data:{attachment.resolve_type()};base64,{base64_content}"
    if attachment.resolve_type().startswith("image/"):
        return {"type": "image_url", "image_url": {"url": url}}
    else:
        format_ = "wav" if attachment.resolve_type() == "audio/wav" else "mp3"
        return {
            "type": "input_audio",
            "input_audio": {
                "data": base64_content,
                "format": format_,
            },
        }
```
As you can see, it uses `attachment.url` if that is available and otherwise falls back to using the `base64_content()` method to embed the image directly in the JSON sent to the API. For the OpenAI API audio attachments are always included as base64-encoded strings.

### Attachments from previous conversations

Models that implement the ability to continue a conversation can reconstruct the previous message JSON using the `response.attachments` attribute.

Here's how the OpenAI plugin does that:

```python
for prev_response in conversation.responses:
    if prev_response.attachments:
        attachment_message = []
        if prev_response.prompt.prompt:
            attachment_message.append(
                {"type": "text", "text": prev_response.prompt.prompt}
            )
        for attachment in prev_response.attachments:
            attachment_message.append(_attachment(attachment))
        messages.append({"role": "user", "content": attachment_message})
    else:
        messages.append(
            {"role": "user", "content": prev_response.prompt.prompt}
        )
    messages.append({"role": "assistant", "content": prev_response.text_or_raise()})
```
The `response.text_or_raise()` method used there will return the text from the response or raise a `ValueError` exception if the response is an `AsyncResponse` instance that has not yet been fully resolved.

This is a slightly weird hack to work around the common need to share logic for building up the `messages` list across both sync and async models.

(advanced-model-plugins-usage)=

## Tracking token usage

Models that charge by the token should track the number of tokens used by each prompt. The ``response.set_usage()`` method can be used to record the number of tokens used by a response - these will then be made available through the Python API and logged to the SQLite database for command-line users.

`response` here is the response object that is passed to `.execute()` as an argument.

Call ``response.set_usage()`` at the end of your `.execute()` method. It accepts keyword arguments `input=`, `output=` and `details=` - all three are optional. `input` and `output` should be integers, and `details` should be a dictionary that provides additional information beyond the input and output token counts.

This example logs 15 input tokens, 340 output tokens and notes that 37 tokens were cached:

```python
response.set_usage(input=15, output=340, details={"cached": 37})
```
