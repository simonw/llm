(openai-models)=

# OpenAI models

LLM ships with a default plugin for talking to OpenAI's API. OpenAI offer both language models and embedding models, and LLM can access both types.

(openai-models-configuration)=

## Configuration

All OpenAI models are accessed using an API key. You can obtain one from [the API keys page](https://platform.openai.com/api-keys) on their site.

Once you have created a key, configure LLM to use it by running:

```bash
llm keys set openai
```
Then paste in the API key.

(openai-models-language)=

## OpenAI language models

Run `llm models` for a full list of available models. The OpenAI models supported by LLM are:

<!-- [[[cog
from click.testing import CliRunner
from llm.cli import cli
result = CliRunner().invoke(cli, ["models", "list"])
models = [line for line in result.output.split("\n") if line.startswith("OpenAI ")]
cog.out("```\n{}\n```".format("\n".join(models)))
]]] -->
```
OpenAI Chat: gpt-4o (aliases: 4o)
OpenAI Chat: gpt-4o-mini (aliases: 4o-mini)
OpenAI Chat: gpt-4.1 (aliases: 4.1)
OpenAI Chat: gpt-4.1-mini (aliases: 4.1-mini)
OpenAI Chat: gpt-4.1-nano (aliases: 4.1-nano)
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k)
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
OpenAI Chat: gpt-4-turbo-2024-04-09
OpenAI Chat: gpt-4-turbo (aliases: gpt-4-turbo-preview, 4-turbo, 4t)
OpenAI Responses: o1
OpenAI Responses: o1-2024-12-17
OpenAI Responses: o3-mini
OpenAI Responses: o3
OpenAI Responses: o4-mini
OpenAI Responses: gpt-5
OpenAI Responses: gpt-5-mini
OpenAI Responses: gpt-5-nano
OpenAI Responses: gpt-5-2025-08-07
OpenAI Responses: gpt-5-mini-2025-08-07
OpenAI Responses: gpt-5-nano-2025-08-07
OpenAI Responses: gpt-5.1
OpenAI Responses: gpt-5.2
OpenAI Responses: gpt-5.2-chat-latest
OpenAI Responses: gpt-5.4
OpenAI Responses: gpt-5.4-2026-03-05
OpenAI Responses: gpt-5.4-mini
OpenAI Responses: gpt-5.4-mini-2026-03-17
OpenAI Responses: gpt-5.4-nano
OpenAI Responses: gpt-5.4-nano-2026-03-17
OpenAI Responses: gpt-5.5
OpenAI Responses: gpt-5.5-2026-04-23
OpenAI Responses: gpt-5.6-sol
OpenAI Responses: gpt-5.6-terra
OpenAI Responses: gpt-5.6-luna
OpenAI Completion: gpt-3.5-turbo-instruct (aliases: 3.5-instruct, chatgpt-instruct)
```
<!-- [[[end]]] -->

See [the OpenAI models documentation](https://platform.openai.com/docs/models) for details of each of these.

`gpt-5.6-luna` is one of the less expensive models, and is the default for if you don't specify a model at all. Consult [OpenAI's model documentation](https://platform.openai.com/docs/models) for details of the other models.

## Model features

The following features work with OpenAI models:

- {ref}`System prompts <usage-system-prompts>` can be used to provide instructions that have a higher weight than the prompt itself.
- {ref}`Attachments <usage-attachments>`. Many OpenAI models support image inputs - check which ones using `llm models --options`. Any model that accepts images can also accept PDFs.
- {ref}`Schemas <usage-schemas>` can be used to influence the JSON structure of the model output.
- {ref}`Model options <usage-model-options>` can be used to set parameters like `temperature`. Use `llm models --options` for a full list of supported options.

(openai-models-code-interpreter)=

## Code Interpreter

Models that use the OpenAI Responses API can run Python in an OpenAI-managed container using the `CodeInterpreter` server-side tool:

```bash
llm -m gpt-5.6-luna -T 'CodeInterpreter(memory_limit="4g")' 'Run this calculation'
```

The same tool can be used from Python:

```python
import llm
from llm.default_plugins.openai_models import CodeInterpreter

model = llm.get_model("gpt-5.6-luna")
response = model.prompt(
    "Use the python tool to calculate 111111 * 333333",
    tools=[CodeInterpreter()],
)
print(response.text())
```

OpenAI calls this Code Interpreter, but models know it as the "python tool", so referring to that name in the prompt is the most explicit way to request it.

By default OpenAI automatically creates a 1 GB container, or reuses an active container from the model's context. Configure a larger automatic container or make existing OpenAI files available to it like this:

```python
CodeInterpreter(
    memory_limit="4g",
    file_ids=["file-1", "file-2"],
)
```

The accepted memory limits are `1g`, `4g`, `16g` and `64g`. Higher limits cost more. To reuse a container that was created separately, pass its ID:

```python
CodeInterpreter(container="cntr_abc123")
```

An explicit container ID cannot be combined with `memory_limit` or `file_ids`. LLM automatically requests the full Code Interpreter output and records returned code and output as server-executed tool parts; it never tries to run that code locally.

OpenAI containers are ephemeral and expire after 20 minutes without activity. See [OpenAI's Code Interpreter documentation](https://developers.openai.com/api/docs/guides/tools-code-interpreter) for container behavior, supported files and current pricing details.

(openai-models-service-tier)=

## Fast mode and service tiers

OpenAI models can process requests at different speeds and prices using the `service_tier` API parameter. [Fast mode](https://developers.openai.com/api/docs/guides/fast-mode) runs up to 2.5x faster than standard processing at a higher per-token price, with the biggest speed increase on `gpt-5.6-sol`. [Flex processing](https://developers.openai.com/api/docs/guides/flex-processing) is slower but cheaper. Each tier works with a different subset of models - the Fast and Flex tables on [OpenAI's pricing page](https://developers.openai.com/api/docs/pricing) are the definitive list of which models support which tier.

All of the OpenAI models supported by LLM expose a `service_tier` option, with the exception of the legacy `gpt-3.5-turbo-instruct` completion model. Use `-o service_tier fast` to enable Fast mode for a prompt:

```bash
llm -m gpt-5.6-sol -o service_tier fast 'Fast facts about pelicans'
```

The value is passed straight to the API, so other tiers such as `priority` (the older name for `fast`) and `flex` ([slower but cheaper processing](https://developers.openai.com/api/docs/guides/flex-processing)) work too:

```bash
llm -m gpt-5.4 -o service_tier flex 'No rush: facts about pelicans'
```

(openai-models-embedding)=

## OpenAI embedding models

Run `llm embed-models` for a list of {ref}`embedding models <embeddings>`. The following OpenAI embedding models are supported by LLM:

```
ada-002 (aliases: ada, oai)
3-small
3-large
3-small-512
3-large-256
3-large-1024
```

The `3-small` model is currently the most inexpensive. `3-large` costs more but is more capable - see [New embedding models and API updates](https://openai.com/blog/new-embedding-models-and-api-updates) on the OpenAI blog for details and benchmarks.

An important characteristic of any embedding model is the size of the vector it returns. Smaller vectors cost less to store and query, but may be less accurate.

OpenAI `3-small` and `3-large` vectors can be safely truncated to lower dimensions without losing too much accuracy. The `-int` models provided by LLM are pre-configured to do this, so `3-large-256` is the `3-large` model truncated to 256 dimensions.

The vector size of the supported OpenAI embedding models are as follows:

| Model | Size |
| --- | --- |
| ada-002 | 1536 |
| 3-small | 1536 |
| 3-large | 3072 |
| 3-small-512 | 512 |
| 3-large-256 | 256 |
| 3-large-1024 | 1024 |

(openai-completion-models)=

## OpenAI completion models

The `gpt-3.5-turbo-instruct` model is a little different - it is a completion model rather than a chat model, described in [the OpenAI completions documentation](https://platform.openai.com/docs/api-reference/completions/create).

(openai-extra-models)=

## Adding more OpenAI models

OpenAI occasionally release new models with new names. LLM aims to ship new releases to support these, but you can also configure them directly, by adding them to a `extra-openai-models.yaml` configuration file.

Run this command to find the directory in which this file should be created:

```bash
dirname "$(llm logs path)"
```
On my Mac laptop I get this:
```
~/Library/Application Support/io.datasette.llm
```
Create a file in that directory called `extra-openai-models.yaml`.

Let's say OpenAI have just released the `gpt-3.5-turbo-0613` model and you want to use it, despite LLM not yet shipping support. You could configure that by adding this to the file:

```yaml
- model_id: gpt-3.5-turbo-0613
  model_name: gpt-3.5-turbo-0613
  aliases: ["0613"]
```
The `model_id` is the identifier that will be recorded in the LLM logs. You can use this to specify the model, or you can optionally include a list of aliases for that model. The `model_name` is the actual model identifier that will be passed to the API, which must match exactly what the API expects.

If the model is a completion model (such as `gpt-3.5-turbo-instruct`) add `completion: true` to the configuration.

If the model should use the OpenAI Responses API rather than Chat Completions, add `responses: true` to the configuration. This is useful for models such as `o1`, `o3-mini` and `gpt-5`-style models that are accessed through `/v1/responses`.

If the model supports structured extraction using json_schema, add `supports_schema: true` to the configuration.

For reasoning models like `o1` or `o3-mini` add `reasoning: true`.

If the model supports the `service_tier` parameter - see {ref}`openai-models-service-tier` - add `service_tier: true` to enable the corresponding option.

With this configuration in place, the following command should run a prompt against the new model:

```bash
llm -m 0613 'What is the capital of France?'
```
Run `llm models` to confirm that the new model is now available:
```bash
llm models
```
Example output:
```
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k)
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
OpenAI Chat: gpt-3.5-turbo-0613 (aliases: 0613)
```
Running `llm logs -n 1` should confirm that the prompt and response has been correctly logged to the database.
