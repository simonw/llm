(model-cards)=
# Model cards

**This is an experimental feature.** Feedback [is welcome](https://github.com/simonw/llm/issues).

Most models are made available by {ref}`installing plugins <installing-plugins>`. Plugins provide the *code* needed to talk to a model - but very often a new model release requires no new code at all, just a new combination of an existing model class and some constructor arguments.

**Executable model cards** solve this. A model card is a Markdown file with YAML frontmatter that describes a model in enough detail for LLM to register it: the plugin that provides the model class, the class itself and the arguments needed to construct it. The Markdown body is a regular human-readable model card - a description of the model, its capabilities and caveats.

This means new models can be added to LLM by installing a single file, without waiting for a plugin release.

## A model card

Here is a card for a hypothetical new Anthropic model, `claude-example.md`:

```yaml
---
model_id: anthropic/claude-example-5
plugin: llm-anthropic
model_class: ClaudeMessages
async_model_class: AsyncClaudeMessages
init:
  model_id: claude-example-5
  supports_pdf: true
  supports_thinking: true
  default_max_tokens: 64000
aliases:
- claude-example
---
# Claude Example 5

A description of the model goes here - release date, capabilities,
pricing, whatever else a human reading the card might want to know.
```

Install it like this:

```bash
llm models cards add claude-example.md
```

Or directly from a URL:

```bash
llm models cards add https://example.com/cards/claude-example-5.md
```

Provided the `llm-anthropic` plugin is installed, the model is now available:

```bash
llm -m claude-example 'Say hello'
```

The card is stored in the directory revealed by `llm models cards path`. Every card in that directory is registered when LLM starts up. Cards are exactly equivalent to models registered by plugin code - aliases, `llm models options`, logging and the rest all work the same way.

## Card format

The YAML frontmatter supports the following keys:

- `model_id`: **required** - the ID the model will be registered under. This should match the `model_id` of the constructed model instance - `llm models cards add` will warn if it does not.
- `model_class`: **required** - the class implementing the model. Either a bare class name such as `ClaudeMessages`, in which case the module is derived from `plugin` (`llm-anthropic` becomes `llm_anthropic`), or a fully qualified dotted path such as `llm_anthropic.ClaudeMessages`.
- `plugin`: the name of the plugin that provides the model class, e.g. `llm-anthropic`. Used to locate the class if `model_class` is not a dotted path, and to suggest `llm install ...` if the class cannot be imported.
- `init`: a dictionary of keyword arguments passed to the model class constructor.
- `async_model_class`: optional class for the async version of the model.
- `async_init`: optional constructor arguments for the async class - defaults to the same as `init`.
- `aliases`: a list of aliases for the model.
- `type`: either `chat` (the default) or `embedding`. Embedding cards are registered as {ref}`embedding models <embeddings>`.

Everything after the closing `---` is the Markdown body. LLM does not interpret it - it is documentation for humans, displayed by `llm models cards show <name>`.

## Managing cards

```bash
# List installed cards, including any that have errors
llm models cards list

# Show the full contents of a card
llm models cards show anthropic-claude-example-5

# Remove a card
llm models cards remove anthropic-claude-example-5

# Show the directory cards are stored in
llm models cards path
```

`llm models cards add` verifies that the card works - that the class can be imported and instantiated - before installing it. If the plugin is not yet installed the card is rejected with a hint; pass `--force` to install the card anyway, for example when preparing an environment before installing its plugins.

A card that stops working - for example because its plugin was uninstalled - does not break LLM. The card is skipped with a warning on standard error and shows up with its error in `llm models cards list`.

## Local models

Cards work with local model plugins too. This card registers a quantized Llama model via [llm-mlx](https://github.com/simonw/llm-mlx), the equivalent of running `llm mlx download-model`:

```yaml
---
model_id: mlx-community/Llama-3.2-3B-Instruct-4bit
plugin: llm-mlx
model_class: MlxModel
init:
  model_path: mlx-community/Llama-3.2-3B-Instruct-4bit
aliases:
- llama-3.2-3b
---
# Llama 3.2 3B Instruct (4bit, MLX)

A 1.8GB quantized model for Apple Silicon. The model itself is
downloaded from Hugging Face on first use.
```

## For plugin authors

Plugins whose `register_models()` implementation is a long list of constructor calls can replace it with a directory of cards bundled with the plugin, using `llm.model_cards.register_model_cards()`:

```python
import pathlib
import llm
from llm.model_cards import register_model_cards

@llm.hookimpl
def register_models(register):
    register_model_cards(
        register, pathlib.Path(__file__).parent / "cards"
    )
```

This turns each supported model into a reviewable, self-documenting file - and those same files can be published individually (in the repository, or attached to a release) so users can adopt newly released models with `llm models cards add <url>` before the next plugin release ships.

There is also `register_embedding_model_cards()` for the `register_embedding_models()` hook.

## Security considerations

A model card cannot introduce new code - it can only instantiate classes from plugins that are already installed. But constructor arguments are still worth reviewing before installing a card from an untrusted source: an argument like `base_url` could redirect prompts (and API keys) to a different server. `llm models cards show` displays exactly what a card will do.
