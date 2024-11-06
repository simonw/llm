(advanced-model-plugins)=
# Advanced model plugins

The {ref}`model plugin tutorial <tutorial-model-plugin>` covers the basics of developing a plugin that adds support for a new model.

This document covers more advanced topics.

(advanced-model-plugins-attachments)=
## Attachments for multi-modal models

Models such as GPT-4o, Claude 3.5 Sonnet and Google's Gemini 1.5 are multi-modal: they accept input in the form of images and maybe even audio, video and other formats.

LLM calls these **attachments**. Models can specify the types of attachments they accept and then implement special code in the `.execute()` method to handle them.

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

**Note:** *MP3 files will have their attachment type detected as `audio/mpeg`, not `audio/mp3`.

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
        format_ = "wav" if attachment.resolve_type() == "audio/wave" else "mp3"
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
    messages.append({"role": "assistant", "content": prev_response.text()})
```
