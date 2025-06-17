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
OpenAI Chat: chatgpt-4o-latest (aliases: chatgpt-4o)
OpenAI Chat: gpt-4o-mini (aliases: 4o-mini)
OpenAI Chat: gpt-4o-audio-preview
OpenAI Chat: gpt-4o-audio-preview-2024-12-17
OpenAI Chat: gpt-4o-audio-preview-2024-10-01
OpenAI Chat: gpt-4o-mini-audio-preview
OpenAI Chat: gpt-4o-mini-audio-preview-2024-12-17
OpenAI Chat: gpt-4.1 (aliases: 4.1)
OpenAI Chat: gpt-4.1-mini (aliases: 4.1-mini)
OpenAI Chat: gpt-4.1-nano (aliases: 4.1-nano)
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k)
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
OpenAI Chat: gpt-4-32k (aliases: 4-32k)
OpenAI Chat: gpt-4-1106-preview
OpenAI Chat: gpt-4-0125-preview
OpenAI Chat: gpt-4-turbo-2024-04-09
OpenAI Chat: gpt-4-turbo (aliases: gpt-4-turbo-preview, 4-turbo, 4t)
OpenAI Chat: gpt-4.5-preview-2025-02-27
OpenAI Chat: gpt-4.5-preview (aliases: gpt-4.5)
OpenAI Chat: o1
OpenAI Chat: o1-2024-12-17
OpenAI Chat: o1-preview
OpenAI Chat: o1-mini
OpenAI Chat: o3-mini
OpenAI Chat: o3
OpenAI Chat: o4-mini
OpenAI Completion: gpt-3.5-turbo-instruct (aliases: 3.5-instruct, chatgpt-instruct)
```
<!-- [[[end]]] -->

See [the OpenAI models documentation](https://platform.openai.com/docs/models) for details of each of these.

`gpt-4o-mini` (aliased to `4o-mini`) is the least expensive model, and is the default for if you don't specify a model at all. Consult [OpenAI's model documentation](https://platform.openai.com/docs/models) for details of the other models.

[o1-pro](https://platform.openai.com/docs/models/o1-pro) is not available  through the Chat Completions API used by LLM's default OpenAI plugin. You can install the new [llm-openai-plugin](https://github.com/simonw/llm-openai-plugin) plugin to access that model.

## Model features

The following features work with OpenAI models:

- {ref}`System prompts <usage-system-prompts>` can be used to provide instructions that have a higher weight than the prompt itself.
- {ref}`Attachments <usage-attachments>`. Many OpenAI models support image inputs - check which ones using `llm models --options`. Any model that accepts images can also accept PDFs.
- {ref}`Schemas <usage-schemas>` can be used to influence the JSON structure of the model output.
- {ref}`Model options <usage-model-options>` can be used to set parameters like `temperature`. Use `llm models --options` for a full list of supported options.

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

Completion models can be called with the `-o logprobs 3` option (not supported by chat models) which will cause LLM to store 3 log probabilities for each returned token in the SQLite database. Consult [this issue](https://github.com/simonw/llm/issues/284#issuecomment-1724772704) for details on how to read these values.

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

If the model supports structured extraction using json_schema, add `supports_schema: true` to the configuration.

For reasoning models like `o1` or `o3-mini` add `reasoning: true`.

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
OpenAI Chat: gpt-4-32k (aliases: 4-32k)
OpenAI Chat: gpt-3.5-turbo-0613 (aliases: 0613)
```
Running `llm logs -n 1` should confirm that the prompt and response has been correctly logged to the database.
