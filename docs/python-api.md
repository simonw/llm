# Python API

LLM provides a Python API for executing prompts, in addition to the command-line interface.

Understanding this API is also important for writing plugins.

## Basic usage

To run a prompt against the `gpt-3.5-turbo` model, run this:

```python
import llm

model = llm.get_model("gpt-3.5-turbo")
model.key = 'YOUR_API_KEY_HERE'
response = model.prompt("Five surprising names for a pet pelican")
print(response.text())
```
The `llm.get_model()` function accepts model names or aliases - so `chatgpt` would work here too.

Run this command to see a list of available models and their aliases:

```bash
llm models list
```

If you have set a `OPENAI_API_KEY` environment variable you can omit the `model.key = ` line.

### Models from plugins

Any models you have installed as plugins will also be available through this mechanism, for example to use Google's PaLM 2 model with [llm-palm](https://github.com/simonw/llm-palm)

```bash
pip install llm-palm
```
```python
import llm

model = llm.get_model("palm")
model.key = 'YOUR_API_KEY_HERE'
response = model.prompt("Five surprising names for a pet pelican")
print(response.text())
```
You can omit the `model.key = ` line for models that do not use an API key

## Concepts

The API consists of the following key concepts:

- `Model` - represents a language model against which prompts can be executed
- `Prompt` - a prompt that can be prepared and then executed against a model
- `Response` - the response executing a prompt against a model
- `Template` - a reusable template for generating prompts

### Prompt

A prompt object represents all of the information needed to be passed to the LLM. This could be a single prompt string, but it might also include a separate system prompt, various settings (for temperature etc) or even a JSON array of previous messages.

### Model

The `Model` class is an abstract base class that needs to be subclassed to provide a concrete implementation. Different LLMs will use different implementations of this class.

Model instances provide the following methods:

- `prompt(prompt: str, stream: bool, ...options) -> Response` - a convenience wrapper which creates a `Prompt` instance and then executes it. This is the most common way to use LLM models.
- `response(prompt: Prompt, stream: bool) -> Response` - execute a prepared Prompt instance against the model and return a `Response`.

Models usually return subclasses of `Response` that are specific to that model.

### Response

The response from an LLM. This could encapusulate a string of text, but for streaming APIs this class will be iterable, with each iteration yielding a short string of text as it is generated.

Calling `.text()` will return the full text of the response, waiting for the stream to stop executing if necessary.

### Template

Templates are reusable objects that can be used to generate prompts. They are used  by the {ref}`prompt-templates` feature.
