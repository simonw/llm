(advanced-model-plugins)=
# Advanced model plugins

The {ref}`model plugin tutorial <tutorial-model-plugin>` covers the basics of developing a plugin that adds support for a new model. This document covers more advanced topics.

Features to consider for your model plugin include:

- {ref}`Accepting API keys <advanced-model-plugins-api-keys>` using the standard mechanism that incorporates `llm keys set`, environment variables and support for passing an explicit key to the model.
- Including support for {ref}`Async models <advanced-model-plugins-async>` that can be used with Python's `asyncio` library.
- Support for {ref}`structured output <advanced-model-plugins-schemas>` using JSON schemas.
- Support for {ref}`tools <advanced-model-plugins-tools>`.
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

The `prompt` object passed to your `execute()` method is an instance of {class}`~llm.Prompt`:

```{eval-rst}
.. autoclass:: llm.Prompt
   :members: prompt, system
   :exclude-members: model, options
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

(advanced-model-plugins-tools)=

## Supporting tools

Adding {ref}`tools support <tools>` involves several steps:

1. Add `supports_tools = True` to your model class.
2. If `prompt.tools` is populated, turn that list of `llm.Tool` objects into the correct format for your model.
3. Look out for requests to call tools in the responses from your model. Call `response.add_tool_call(llm.ToolCall(...))` for each of those. This should work for streaming and non-streaming and async and non-async cases.
4. If your prompt has a `prompt.tool_results` list, pass the information from those `llm.ToolResult` objects to your model.
5. Include `prompt.tools` and `prompt.tool_results` and tool calls from `response.tool_calls_or_raise()` in the conversation history constructed by your plugin.
6. Make sure your code is OK with prompts that do not have `prompt.prompt` set to a value, since they may be carrying exclusively the results of a tool call.

This [commit to llm-gemini](https://github.com/simonw/llm-gemini/commit/a7f1096cfbb733018eb41c29028a8cc6160be298) implementing tools helps demonstrate what this looks like for a real plugin.

Here are the relevant dataclasses:

```{eval-rst}
.. autoclass:: llm.Tool

.. autoclass:: llm.ToolCall

.. autoclass:: llm.ToolResult
```


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

Conversation history — including attachments from prior turns — is available on the canonical `prompt.messages` list. See the [next section](#structured-messages-streaming) for how that works.

(structured-messages-streaming)=

## Structured messages and streaming events

The 0.32 alpha introduced a richer contract for plugins than "yield strings":

1. **`execute()` yields `StreamEvent` objects** (or plain `str`, still supported) so text, reasoning (thinking tokens), tool calls, and server-side tool results each surface as their own event type. The framework assembles these into typed `Part` objects.
2. **`build_messages` (or equivalent) reads `prompt.messages`** — a `list[llm.Message]` that is the complete input chain for this turn.
3. **Opaque provider tokens round-trip via `provider_metadata`** — Anthropic thinking signatures, Gemini thought signatures, OpenAI Responses API encrypted reasoning blobs. Plugins stash whatever the API returns, then echo it back on the next request.

**Older plugins still work.** A plugin that still yields plain `str` from `execute()` works unchanged — each string is wrapped as a `StreamEvent(type="text", chunk=...)` internally.

### Yielding StreamEvent from execute()

```python
from llm.parts import StreamEvent

def execute(self, prompt, stream, response, conversation, key=None):
    messages = self.build_messages(prompt, conversation)
    ...

    for chunk in provider_sdk.stream(...):
        if chunk.type == "text":
            yield StreamEvent(type="text", chunk=chunk.text)
        elif chunk.type == "thinking":
            yield StreamEvent(type="reasoning", chunk=chunk.text)
```

A `StreamEvent` has four frequently-used fields:

- **`type`** — one of `"text"`, `"reasoning"`, `"tool_call_name"`, `"tool_call_args"`, `"tool_result"`.
- **`chunk`** — the text fragment. For tool calls this is the tool name (for `tool_call_name`) or a partial JSON string (for `tool_call_args`).
- **`tool_call_id`** — the provider's id for the tool call, set on `tool_call_name` / `tool_call_args` / `tool_result` events. Also the signal the framework uses to group tool-call events into one `ToolCallPart`.
- **`provider_metadata`** — an optional `dict[str, dict]` namespaced by provider name. Carries opaque data (signatures, encrypted blobs) that must be echoed back on future requests.

Three additional fields exist for special cases:

- **`server_executed: bool`** — set `True` for server-side tool calls (for example, Anthropic web search) and their results. This means the model ran the tool internally as part of responding to the prompt.
- **`tool_name`** — set on `tool_result` events to identify which tool this result came from.
- **`part_index: int | None`** — defaults to `None`, which means "let the framework decide which Part this event belongs to." Pass an explicit integer only when you need to override the default grouping (see [below](#part-index-overrides)).

### How events group into Parts

When you leave `part_index` as `None` (the default), the framework groups events using these rules:

- **Consecutive same-family events concatenate.** Two `text` events in a row become one `TextPart`. Two `reasoning` events in a row become one `ReasoningPart`. A family transition (text → reasoning, or reasoning → text) starts a new Part.
- **Tool calls group by `tool_call_id`.** A `tool_call_name` and any number of `tool_call_args` events sharing a `tool_call_id` combine into one `ToolCallPart` — even if they're interleaved with other events (parallel tool calls).
- **`tool_result` is always its own Part**, paired to the originating call by `tool_call_id`.

| Stream                                    | Resulting Parts                                          |
|-------------------------------------------|----------------------------------------------------------|
| `text` × N                                | one `TextPart`                                           |
| `reasoning` × N, then `text` × N          | `ReasoningPart`, `TextPart`                              |
| `text`, `tool_call_name`+`args`, `text`   | `TextPart`, `ToolCallPart`, `TextPart`                   |
| Parallel tool calls (interleaved by id)   | one `ToolCallPart` per distinct `tool_call_id`           |
| `reasoning`, tool call, `reasoning`       | `ReasoningPart`, `ToolCallPart`, `ReasoningPart`         |

(part-index-overrides)=
### Setting `part_index` explicitly

In rare cases you'll want to override the default grouping:

- **Forcing a single TextPart across non-adjacent text bursts.** If your provider interleaves text deltas with tool calls but you want all the text concatenated into one `TextPart`, pass `part_index=0` on every text event. (The default behavior produces separate `TextPart`s on each side of the tool calls — usually what you want, but not always.)
- **Tool-call args arriving before the id.** If your provider streams args before the `tool_call_id` is known, assign your own index per logical tool call and pass it on each event of that call.

You can mix explicit indices with `None` in the same stream — the framework reserves your explicit values and decides the rest.

### Reasoning tokens

For streamed reasoning text:

```python
yield StreamEvent(type="reasoning", chunk=text_chunk)
```

Reasoning events that appear before/after text events become distinct `ReasoningPart` and `TextPart` entries in `response.messages` automatically. If your provider emits two thinking blocks separated by a tool call, you'll get two `ReasoningPart`s.

Plugins should respect `prompt.hide_reasoning`. This is set when the caller passes `hide_reasoning=True` to `model.prompt()`, `conversation.prompt()`, `model.chain()`, `conversation.chain()`, or their async counterparts. It is also set by the CLI `-R/--hide-reasoning` option.

`prompt.hide_reasoning` means "hide visible reasoning output", not "disable model reasoning". If your provider requires an explicit request for visible reasoning summaries, do not request those summaries when `prompt.hide_reasoning` is true:

```python
kwargs = {}
if not prompt.hide_reasoning:
    kwargs["reasoning"] = {"summary": "auto"}
```

If your provider emits reasoning blocks regardless of request parameters, keep yielding those reasoning events as usual:

```python
if chunk.type == "thinking":
    yield StreamEvent(type="reasoning", chunk=chunk.text)
```

LLM's display layers use `prompt.hide_reasoning` to avoid showing those events to the user, while still allowing the framework to persist `ReasoningPart` objects and provider metadata for logs, serialization, and future turns.

### Tool calls

Each tool call emits two event types sharing a `tool_call_id`:

```python
yield StreamEvent(
    type="tool_call_name",
    chunk=tool_name,
    tool_call_id=tool_call_id,
)
# then, as the provider streams JSON args:
yield StreamEvent(
    type="tool_call_args",
    chunk=partial_json_fragment,
    tool_call_id=tool_call_id,
)
```

The framework groups them by `tool_call_id` — so parallel tool calls (where args for tool A and tool B interleave on the wire) work without any per-call index tracking. Some providers (Gemini) emit the complete tool call in one chunk — it's OK to emit both events back-to-back with the full name and full JSON.

For client-side tool calls — tools that LLM should execute locally in a chain — **also call `response.add_tool_call()`**. The chain-execution path (`response.tool_calls()` → `execute_tool_calls()`) reads from the explicitly-added list, not from the StreamEvent buffer.

```python
response.add_tool_call(
    llm.ToolCall(
        tool_call_id=tool_id,
        name=tool_name,
        arguments=parsed_args,
    )
)
```

### Server-side tool calls

For tools the API executes internally, set `server_executed=True` on the events. Anthropic web search is an example: the API returns a `server_tool_use` block for the search request, followed by a `web_search_tool_result` block containing the result payload.

```python
yield StreamEvent(
    type="tool_call_name",
    chunk="web_search",
    tool_call_id=tool_id,
    server_executed=True,
)
yield StreamEvent(
    type="tool_call_args",
    chunk=json.dumps(query_args),
    tool_call_id=tool_id,
    server_executed=True,
)
```

The tool *result* (for example, the search hits) is also emitted as an event:

```python
yield StreamEvent(
    type="tool_result",
    chunk=human_readable_summary,
    tool_call_id=tool_id,
    server_executed=True,
    tool_name="web_search",
    provider_metadata={"myprovider": {"raw_content": full_payload}},
)
```

For providers that don't stream server-tool-result contents (Anthropic's `web_search_tool_result` blocks only arrive in the final message), emit those results as a post-stream step. After the main iteration loop completes, inspect the final message and emit tool_result events for any server-side results.

Do **not** call `response.add_tool_call()` for server-side tool calls. This method should only be used for tool calls that need to be executed locally by the framework.

### Opaque provider metadata

Some providers require you to echo back opaque fields on the next request for multi-turn continuity to work:

- **Anthropic** — `signature` on each thinking block; `encrypted_content` inside web_search_tool_result items.
- **Google Gemini** — `thoughtSignature` on `functionCall` parts when thinking is active.
- **OpenAI Responses API** — `encrypted_content` on reasoning items in stateless mode.

These values are attached to a `StreamEvent` via its `provider_metadata` field. The framework merges metadata across events that group into the same Part (last non-None wins per top-level key) and persists it on the finalized Part.

Namespace under your provider's name so transcripts that mix providers don't collide:

```python
# Anthropic signature arrives at the end of a thinking block.
yield StreamEvent(
    type="reasoning",
    chunk="",
    provider_metadata={"anthropic": {"signature": sig}},
)
```

```python
# Gemini attaches thoughtSignature to a functionCall part.
yield StreamEvent(
    type="tool_call_name",
    chunk=name,
    tool_call_id=tc_id,
    provider_metadata={"gemini": {"thoughtSignature": sig}},
)
```

The framework round-trips the value verbatim via JSON, so use JSON-safe primitives (string, int, bool, dict, list) for provider metadata - use base64 encoding if you need to store binary data.

### Non-streaming path

When `stream=False` (or the provider returns a complete message at once), emit one event per content block.

```python
else:
    completion = client.messages.create(**kwargs)
    response.response_json = completion.model_dump()
    for block in completion.content:
        if block.type == "thinking":
            yield StreamEvent(
                type="reasoning",
                chunk=block.thinking,
                provider_metadata={"anthropic": {"signature": block.signature}},
            )
        elif block.type == "text":
            yield StreamEvent(type="text", chunk=block.text)
        elif block.type == "tool_use":
            yield StreamEvent(
                type="tool_call_name",
                chunk=block.name,
                tool_call_id=block.id,
            )
            yield StreamEvent(
                type="tool_call_args",
                chunk=json.dumps(block.input),
                tool_call_id=block.id,
            )
```

## Consuming prompt.messages in build_messages

`prompt.messages` is an `list[llm.Message]` that is always **the complete input chain for this turn** — whether the caller supplied it explicitly via `model.prompt(messages=[...])`, or it was synthesized from kwargs (`prompt=`, `system=`, `attachments=`, `tool_results=`), or it was pre-built by a `Conversation` or by `response.reply()`.

**Do not also walk `conversation.responses`.** History is already baked into `prompt.messages`; walking the conversation would double-emit.

A plugin's `build_messages` (or equivalent) iterates `prompt.messages` and dispatches per `Part` subtype:

```python
from llm.parts import (
    TextPart,
    ReasoningPart,
    ToolCallPart,
    ToolResultPart,
    AttachmentPart,
)

def build_messages(self, prompt, conversation):
    messages = []
    for msg in prompt.messages:
        if msg.role == "system":
            # Some APIs put system on a separate kwarg (Anthropic, Gemini).
            # OpenAI-style APIs emit it as a message; handle accordingly.
            continue
        self._append_message(messages, msg)
    return messages

def _append_message(self, out, msg):
    # Map llm's role to the provider's (assistant→model for Gemini,
    # tool→user for Anthropic/Gemini tool_result convention, etc.)
    role = self._provider_role(msg.role)
    parts = []
    for part in msg.parts:
        if isinstance(part, TextPart):
            parts.append({"type": "text", "text": part.text})
        elif isinstance(part, ReasoningPart):
            # Skip redacted reasoning (no content to echo back).
            if part.redacted or not part.text:
                continue
            block = {"type": "thinking", "thinking": part.text}
            # Restore the signature from provider_metadata.
            sig = (part.provider_metadata or {}).get("anthropic", {}).get("signature")
            if sig:
                block["signature"] = sig
            parts.append(block)
        elif isinstance(part, ToolCallPart):
            parts.append({
                "type": "tool_use",
                "id": part.tool_call_id,
                "name": part.name,
                "input": part.arguments,
            })
        elif isinstance(part, ToolResultPart):
            parts.append({
                "type": "tool_result",
                "tool_use_id": part.tool_call_id,
                "content": part.output,
            })
        elif isinstance(part, AttachmentPart) and part.attachment:
            parts.append(self._attachment_block(part.attachment))
    # Merge with the previous message if roles match (some providers
    # require strict alternation between user and assistant).
    if out and out[-1]["role"] == role:
        out[-1]["content"].extend(parts)
    else:
        out.append({"role": role, "content": parts})
```

## Restoring opaque metadata on subsequent requests

When a conversation continues, your `build_messages` walks prior-turn Parts via `prompt.messages`. Each Part's `provider_metadata` is a `dict[str, dict]` keyed by provider name — extract your namespace and fold the fields back into the outgoing request body:

```python
if isinstance(part, ReasoningPart):
    block = {"type": "thinking", "thinking": part.text}
    pm = (part.provider_metadata or {}).get("anthropic", {})
    if "signature" in pm:
        block["signature"] = pm["signature"]
    parts.append(block)

if isinstance(part, ToolCallPart):
    fc_part = {"function_call": {"name": part.name, "args": part.arguments}}
    pm = (part.provider_metadata or {}).get("gemini", {})
    if "thoughtSignature" in pm:
        # Gemini expects thoughtSignature beside function_call,
        # not nested inside it.
        fc_part["thoughtSignature"] = pm["thoughtSignature"]
    parts.append(fc_part)
```

If the key is missing (an older transcript that pre-dates your plugin's support), fall through — don't fail. Treat other providers' entries as opaque; don't parse them.

(advanced-model-plugins-usage)=

## Tracking token usage

Models that charge by the token should track the number of tokens used by each prompt. The ``response.set_usage()`` method can be used to record the number of tokens used by a response - these will then be made available through the Python API and logged to the SQLite database for command-line users.

`response` here is the response object that is passed to `.execute()` as an argument.

Call ``response.set_usage()`` at the end of your `.execute()` method. It accepts keyword arguments `input=`, `output=` and `details=` - all three are optional. `input` and `output` should be integers, and `details` should be a dictionary that provides additional information beyond the input and output token counts.

This example logs 15 input tokens, 340 output tokens and notes that 37 tokens were cached:

```python
response.set_usage(input=15, output=340, details={"cached": 37})
```
(advanced-model-plugins-resolved-model)=

## Tracking resolved model names

In some cases the model ID that the user requested may not be the exact model that is executed. Many providers have a `model-latest` alias which may execute different models over time.

If those APIs return the _real_ model ID that was used, your plugin can record that in the `resources.resolved_model` column in the logs by calling this method and passing the string representing the resolved, final model ID:

```bash
response.set_resolved_model(resolved_model_id)
```
This string will be recorded in the database and shown in the output of `llm logs` and `llm logs --json`.

(tutorial-model-plugin-raise-errors)=

## LLM_RAISE_ERRORS

While working on a plugin it can be useful to request that errors are raised instead of being caught and logged, so you can access them from the Python debugger.

Set the `LLM_RAISE_ERRORS` environment variable to enable this behavior, then run `llm` like this:

```bash
LLM_RAISE_ERRORS=1 python -i -m llm ...
```
The `-i` option means Python will drop into an interactive shell if an error occurs. You can then open a debugger at the most recent error using:

```python
import pdb; pdb.pm()
```
