(other-models)=
# Other models

LLM supports OpenAI models by default. You can install {ref}`plugins` to add support for other models. You can also add additional OpenAI-compatible models {ref}`using a configuration file <openai-extra-models>`.

## Installing and using a local model

{ref}`LLM plugins <plugins>` can provide local models that run on your machine.

To install **[llm-gpt4all](https://github.com/simonw/llm-gpt4all)**, providing 17 models from the [GPT4All](https://gpt4all.io/) project, run this:

```bash
llm install llm-gpt4all
```
Run `llm models list` to see the expanded list of available models.

To run a prompt through one of the models from GPT4All specify it using `-m/--model`:
```bash
llm -m ggml-vicuna-7b-1 'What is the capital of France?'
```
The model will be downloaded and cached the first time you use it.

Check the **[llm-plugins](https://github.com/simonw/llm-plugins)** repository for the latest list of available plugins for other models.

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

With this configuration in place, the following command should run a prompt against the new model:

```bash
llm -m 0613 'What is the capital of France?'
```
Run `llm models list` to confirm that the new model is now available:
```bash
llm models list
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
