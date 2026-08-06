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

(openai-endpoint)=
### Run against an endpoint without configuring it

Use `llm openai endpoint` to run a prompt directly against an OpenAI-compatible base URL:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  "What is the capital of France?"
```

This command does not register the model and does not log the prompt or response. It also does not send your configured OpenAI API key to the endpoint. Use `--key` to explicitly provide a key or the alias of a key saved using `llm keys set`:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  --key custom-endpoint \
  "What is the capital of France?"
```

List the model IDs advertised by the endpoint using `--models`. This requests the `models` resource relative to the base URL, so a base URL ending in `/v1` will request `/v1/models`:

```bash
llm openai endpoint https://example.com/v1 --models
```

Omit the prompt to read it from stdin. In an interactive terminal the command waits for input until EOF, matching `llm prompt`:

```bash
llm openai endpoint https://example.com/v1 -m model-id
```

Use `--chat` to start an interactive chat:

```bash
llm openai endpoint https://example.com/v1 -m model-id --chat
```

Use `-a` or `--attachment` to attach an image or PDF. Chat Completions endpoints can also receive WAV or MP3 audio attachments:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  -a image.jpg \
  "Describe this image"
```

Use `--at path-or-url mimetype` when the attachment type cannot be inferred. Attachments provided when starting an interactive chat are included with the first message.

Use `-t` or `--template` to apply an existing LLM template. Template prompts, system prompts, defaults, model options, model IDs, schemas, and attachments are supported. Pass template variables using `-p` or `--param`:

```bash
llm openai endpoint https://example.com/v1 \
  -t summarize \
  -p style concise \
  "Text to summarize"
```

The `-m` option can be omitted if the template specifies a model. In an interactive chat started using `--chat`, the template is applied to each turn. Without `--chat`, a template that provides its own prompt runs once even when no prompt argument is supplied.

Use `--schema` to request structured JSON output or `--schema-multi` to request an array of matching items. These accept the same inline JSON, file paths, stored schema IDs, template references and {ref}`concise schema syntax <schemas-dsl>` as `llm prompt`:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  --schema 'name, age int' \
  "Invent a dog"
```

Reasoning-capable endpoints can be given a reasoning effort using `-o reasoning_effort`, with a value of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  -o reasoning_effort high \
  "Solve this problem"
```

The command does not send reasoning-specific request fields by default and does not request a reasoning summary. Those fields are only added when `reasoning_effort` is used. An endpoint that does not support the option will return its own API error.

Use `-T` or `--tool` to make an installed LLM tool available to the model, or `--functions` to load Python functions from an inline code block or file:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  -T llm_time \
  --functions tools.py \
  "What time is it?"
```

Tool calls are executed locally and their results are sent back to the endpoint until it returns a final answer. `--chain-limit` controls the maximum number of responses, `--tools-debug` shows tool execution details, and `--tools-approve` asks for confirmation before each call. Tools and trusted Python functions declared by local templates are supported too.

The command uses the Chat Completions API by default. Add `--responses` for an endpoint that implements the Responses API:

```bash
llm openai endpoint https://example.com/v1 \
  -m model-id \
  --responses \
  "What is the capital of France?"
```

Responses endpoints can define their own server-side tool types. Use `ServerSideTool` to pass an endpoint-specific tool specification through without validation. For example, [OpenRouter's web search server tool](https://openrouter.ai/docs/api/reference/responses/web-search) can be used like this:

```bash
llm openai endpoint https://openrouter.ai/api/v1 \
  -m openai/gpt-oss-20b:free \
  --key openrouter \
  --responses \
  -R \
  -T 'ServerSideTool(spec={"type":"openrouter:web_search","parameters":{"engine":"exa","max_results":2,"max_uses":1}})' \
  "Search for the OpenRouter documentation URL"
```

`-R` hides the reasoning text returned by this model so the command displays just its final answer.

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


### Cloud LLM API gateways

API gateway services such as [OfoxAI](https://ofox.ai) provide access to 100+ models (GPT, Claude, Gemini, DeepSeek, etc.) through a single OpenAI-compatible endpoint:

```yaml
- model_id: ofoxai-gpt-4o
  model_name: gpt-4o
  api_base: "https://api.ofox.ai/v1"
  api_key_name: ofoxai
```

Store your OfoxAI API key with:

```bash
llm keys set ofoxai
```

You can then swap `model_name` to any of the [100+ models](https://ofox.ai) OfoxAI supports without changing your API key.
