(plugin-utilities)=
# Utility functions for plugins

LLM provides some utility functions that may be useful to plugins.

## llm.user_dir()

LLM stores various pieces of logging and configuration data in a directory on the user's machine.

On macOS this directory is `~/Library/Application Support/io.datasette.llm`, but this will differ on other operating systems.

The `llm.user_dir()` function returns the path to this directory as a `pathlib.Path` object.

Plugins can use this to store their own data in a subdirectory of this directory.

```python
import llm
user_dir = llm.user_dir()
plugin_dir = data_path = user_dir / "my-plugin"
plugin_dir.mkdir(exist_ok=True)
data_path = plugin_dir / "plugin-data.db"
```

## llm.ModelError

If your model encounters an error that should be reported to the user you can raise this exception. For example:

```python
import llm

raise ModelError("MPT model not installed - try running 'llm mpt30b download'")
```
This will be caught by the CLI layer and displayed to the user as an error message.

## Response.fake()

When writing tests for a model it can be useful to generate fake response objects, for example in this test from [llm-mpt30b](https://github.com/simonw/llm-mpt30b):

```python
def test_build_prompt_conversation():
    model = llm.get_model("mpt")
    conversation = model.conversation()
    conversation.responses = [
        llm.Response.fake(model, "prompt 1", "system 1", "response 1"),
        llm.Response.fake(model, "prompt 2", None, "response 2"),
        llm.Response.fake(model, "prompt 3", None, "response 3"),
    ]
    lines = model.build_prompt(llm.Prompt("prompt 4", model), conversation)
    assert lines == [
        "<|im_start|>system\system 1<|im_end|>\n",
        "<|im_start|>user\nprompt 1<|im_end|>\n",
        "<|im_start|>assistant\nresponse 1<|im_end|>\n",
        "<|im_start|>user\nprompt 2<|im_end|>\n",
        "<|im_start|>assistant\nresponse 2<|im_end|>\n",
        "<|im_start|>user\nprompt 3<|im_end|>\n",
        "<|im_start|>assistant\nresponse 3<|im_end|>\n",
        "<|im_start|>user\nprompt 4<|im_end|>\n",
        "<|im_start|>assistant\n",
    ]
```
The signature of `llm.Response.fake()` is:

```python
def fake(cls, model: Model, prompt: str, system: str, response: str):
```
