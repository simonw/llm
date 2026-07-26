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

### Run against an endpoint without configuring it

Use `llm openai endpoint` to run a prompt directly against an
OpenAI-compatible base URL:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  "What is the capital of France?"
```

This command does not register the model and does not log the prompt or
response. It also does not send your configured OpenAI API key to the endpoint.
Use `--key` to explicitly provide a key or the alias of a key saved using
`llm keys set`:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  --key custom-endpoint \
  "What is the capital of France?"
```

List the model IDs advertised by the endpoint using `--models`. This requests
the `models` resource relative to the base URL, so a base URL ending in `/v1`
will request `/v1/models`:

```bash
llm openai endpoint https://example.com/v1 --models
```

Omit the prompt to start an interactive chat:

```bash
llm openai endpoint https://example.com/v1 -m model-id
```

Piped stdin is treated as a one-off prompt. Use `--chat` to explicitly start
an interactive chat when stdin is not a terminal.

Use `-a` or `--attachment` to attach an image or PDF. Chat Completions
endpoints can also receive WAV or MP3 audio attachments:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  -a image.jpg \
  "Describe this image"
```

Use `--at path-or-url mimetype` when the attachment type cannot be inferred.
Attachments provided when starting an interactive chat are included with the
first message.

The command uses the Chat Completions API by default. Add `--responses` for an
endpoint that implements the Responses API:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  --responses \
  "What is the capital of France?"
```

### Configure an OpenAI-compatible model

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

Other keys you can use here:

- `completion: true` for completion models that should use the `/completion` endpoint as opposed to `/completion/chat`
- `responses: true` for models that should use the OpenAI Responses API (`/responses`) instead of the Chat Completions API (`/chat/completions`)
- `supports_tools: true` for models that support tool calling
- `can_stream: false` to disable streaming mode for models that cannot stream
- `supports_schema: true` for models that support JSON structured schema output
- `vision: true` for models that can accept images as input
- `audio: true` for models that accept audio attachments

Having configured the model like this, run `llm models --options -m MODEL_ID` to check that it installed correctly. You can then run prompts against it like so:

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
