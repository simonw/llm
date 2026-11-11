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

Responses API endpoints can also be asked for a visible reasoning summary using `-o reasoning_summary`, with a value of `auto`, `concise`, or `detailed`:

```bash
llm openai endpoint https://example.com/v1 \
  --responses \
  -m model-id \
  -o reasoning_summary auto \
  "Solve this problem"
```

This maps to the Responses API `reasoning.summary` request field. `auto` asks the endpoint for the most detailed summary available for that model. Use `-R` or `--hide-reasoning` to suppress summary generation for a request.

The command does not send reasoning-specific request fields by default and does not request a reasoning summary unless one of these options is used. An endpoint that does not support an option will return its own API error.

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

(openai-endpoint-add)=
### Configure an OpenAI-compatible model

Once you have found an endpoint and model that work, save them to the `extra-openai-models.yaml` configuration file so the model can be used with `llm -m MODEL_ID`, and logged, like any other model. The `llm openai endpoint add` command writes that file for you.

To add the `orca-mini-3b` model hosted by a local installation of [LocalAI](https://localai.io/):

```bash
llm openai endpoint add http://localhost:8080 \
  -m orca-mini-3b.ggmlv3 \
  --id orca-openai-compat
```

This appends the following record to the file:

```yaml
- model_id: orca-openai-compat
  model_name: orca-mini-3b.ggmlv3
  api_base: http://localhost:8080
```

The `model_id` is the name LLM will use for the model. The `model_name` is the name which needs to be passed to the API - this might differ from the `model_id`, especially if the `model_id` could potentially clash with other installed models. `--id` defaults to the model name if you omit it.

The `api_base` key points the OpenAI client library at a different API endpoint. If `api_base` is set, the existing configured `openai` API key will not be sent by default.

Use `--key NAME` to send a key stored using the {ref}`api-keys` feature instead. This is written as `api_key_name` in the file - the key itself is never stored there, so the name must already exist in `llm keys list`:

```bash
llm keys set openrouter
llm openai endpoint add https://openrouter.ai/api/v1 \
  -m anthropic/claude-sonnet-4.5 \
  --id claude-sonnet \
  --alias claude \
  --key openrouter \
  --supports-tools --vision
```

The other options correspond to keys in the YAML file:

- `--alias NAME` adds an alias, written to the `aliases` list. Repeat it for multiple aliases.
- `--completion` writes `completion: true` for completion models that should use the `/completion` endpoint as opposed to `/completion/chat`
- `--responses` writes `responses: true` for models that should use the OpenAI Responses API (`/responses`) instead of the Chat Completions API (`/chat/completions`)
- `--supports-tools` writes `supports_tools: true` for models that support tool calling
- `--no-stream` writes `can_stream: false` to disable streaming mode for models that cannot stream
- `--supports-schema` writes `supports_schema: true` for models that support JSON structured schema output
- `--vision` writes `vision: true` for models that can accept images as input
- `--audio` writes `audio: true` for models that accept audio attachments
- `--reasoning` writes `reasoning: true` for reasoning models
- `--service-tier` writes `service_tier: true` for models that support the `service_tier` option
- `--api-type`, `--api-version` and `--api-engine` write the corresponding keys, used for Azure OpenAI deployments

Adding a model with an ID that is already in the file is an error. Pass `--replace` to overwrite that record instead.

You can also edit the file by hand. `llm openai endpoint path` outputs its location, and `add` appends to the end of the file without rewriting your existing records, so comments and formatting are preserved. `--replace` and `remove` do rewrite the file, which drops any comments.

Having configured the model like this, run `llm models --options -m MODEL_ID` to check that it installed correctly. You can then run prompts against it like so:

```bash
llm -m orca-openai-compat 'What is the capital of France?'
```
And confirm they were logged correctly with:
```bash
llm logs -n 1
```

Some OpenAI-compatible Chat Completions servers support provider-specific chat template arguments. These can be saved in a reusable template using the `chat_template_kwargs` option. For example, a server using `enable_thinking` could use a template like this:

```yaml
model: orca-openai-compat
prompt: $input
options:
  chat_template_kwargs:
    enable_thinking: false
```

The nested keys are defined by the provider, not by LLM. The equivalent command-line option accepts a JSON object:

```bash
llm -m orca-openai-compat \
  -o chat_template_kwargs '{"enable_thinking": false}' \
  "What is the capital of France?"
```

### Listing and removing configured models

`llm openai endpoint list` shows the records in the file, or `--json` for the raw records:

```bash
llm openai endpoint list
```
```
orca-openai-compat: orca-mini-3b.ggmlv3 at http://localhost:8080
claude-sonnet: anthropic/claude-sonnet-4.5 at https://openrouter.ai/api/v1 (aliases: claude)
```

`llm openai endpoint remove MODEL_ID` deletes a record:

```bash
llm openai endpoint remove orca-openai-compat
```

### Extra HTTP headers

Some providers such as [openrouter.ai](https://openrouter.ai/docs) may require the setting of additional HTTP headers. Pass `-H/--header` to `llm openai endpoint add`, or set them using the `headers:` key like this:

```yaml
- model_id: claude
  model_name: anthropic/claude-2
  api_base: "https://openrouter.ai/api/v1"
  api_key_name: openrouter
  headers:
    HTTP-Referer: "https://llm.datasette.io/"
    X-Title: LLM
```
