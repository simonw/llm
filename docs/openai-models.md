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

```
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k, turbo)
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
OpenAI Chat: gpt-4-32k (aliases: 4-32k)
OpenAI Chat: gpt-4-1106-preview
OpenAI Chat: gpt-4-0125-preview
OpenAI Chat: gpt-4-turbo-preview (aliases: gpt-4-turbo, 4-turbo, 4t)
OpenAI Completion: gpt-3.5-turbo-instruct (aliases: 3.5-instruct, chatgpt-instruct, instruct)
```

See [the OpenAI models documentation](https://platform.openai.com/docs/models) for details of each of these.

The best balance of price and capacity are the `-turbo` models. `gpt-3.5-turbo` (aliased to `3.5`) is the least expensive. `gpt-4-turbo-preview` (aliased to `4t`) is the cheapest of the GPT-4 models.

The `gpt-3.5-turbo-instruct` model is a little different - it is a completion model rather than a chat model, described in [the OpenAI completions documentation](https://platform.openai.com/docs/api-reference/completions/create).

Completion models can be called with the `-o logprobs 3` option (not supported by chat models) which will cause LLM to store 3 log probabilities for each returned token in the SQLite database. Consult [this issue](https://github.com/simonw/llm/issues/284#issuecomment-1724772704) for details on how to read these values.

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
  aliases: ["0613"]
```
The `model_id` is the identifier that will be recorded in the LLM logs. You can use this to specify the model, or you can optionally include a list of aliases for that model.

If the model is a completion model (such as `gpt-3.5-turbo-instruct`) add `completion: true` to the configuration.

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
