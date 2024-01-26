(other-models)=
# Other models

LLM supports OpenAI models by default. You can install {ref}`plugins <plugins>` to add support for other models. You can also add additional OpenAI-API-compatible models {ref}`using a configuration file <openai-extra-models>`.

## Installing and using a local model

{ref}`LLM plugins <plugins>` can provide local models that run on your machine.

To install **[llm-gpt4all](https://github.com/simonw/llm-gpt4all)**, providing 17 models from the [GPT4All](https://gpt4all.io/) project, run this:

```bash
llm install llm-gpt4all
```
Run `llm models` to see the expanded list of available models.

To run a prompt through one of the models from GPT4All specify it using `-m/--model`:
```bash
llm -m orca-mini-3b-gguf2-q4_0 'What is the capital of France?'
```
The model will be downloaded and cached the first time you use it.

Check the {ref}`plugin directory <plugin-directory>` for the latest list of available plugins for other models.

(openai-compatible-models)=

## OpenAI-compatible models

Projects such as [LocalAI](https://localai.io/) offer a REST API that imitates the OpenAI API but can be used to run other models, including models that can be installed on your own machine. These can be added using the same configuration mechanism.

The `model_id` is the name LLM will use for the model. The `model_name` is the name which needs to be passed to the API - this might differ from the `model_id`, especially if the `model_id` could potentially clash with other installed models.

The `api_base` key can be used to point the OpenAI client library at a different API endpoint.

To add the `orca-mini-3b` model hosted by a local installation of [LocalAI](https://localai.io/), add this to your `extra-openai-models.yaml` file:

```yaml
- model_id: orca-openai-compat
  model_name: orca-mini-3b.ggmlv3
  api_base: "http://localhost:8080"
```
If the `api_base` is set, the existing configured `openai` API key will not be sent by default.

You can set `api_key_name` to the name of a key stored using the {ref}`api-keys` feature.

Add `completion: true` if the model is a completion model that uses a `/completion` as opposed to a `/completion/chat` endpoint.

Having configured the model like this, run `llm models` to check that it installed correctly. You can then run prompts against it like so:

```bash
llm -m orca-openai-compat 'What is the capital of France?'
```
And confirm they were logged correctly with:
```bash
llm logs -n 1
```

### Extra HTTP headers

Some providers such as [openrouter.ai](https://openrouter.ai/docs) may require the setting of additional HTTP headers. You can set those using the `headers:` key like this:

```yaml
- model_id: claude
  model_name: anthropic/claude-2
  api_base: "https://openrouter.ai/api/v1"
  api_key_name: openrouter
  headers:
    HTTP-Referer: "https://llm.datasette.io/"
    X-Title: LLM
```