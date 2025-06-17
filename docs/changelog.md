# Changelog

(v0_26)=
## 0.26 (2025-05-27)

**Tool support** is finally here! This release adds support exposing {ref}`tools <tools>` to LLMs, previously described in the release notes for {ref}`0.26a0 <v0_26_a0>` and {ref}`0.26a1 <v0_26_a1>`.

Read **[Large Language Models can run tools in your terminal with LLM 0.26](https://simonwillison.net/2025/May/27/llm-tools/)** for a detailed overview of the new features.

Also in this release:

- Two new {ref}`default tools <tools-default>`: `llm_version()` and `llm_time()`. [#1096](https://github.com/simonw/llm/issues/1096), [#1103](https://github.com/simonw/llm/issues/1103)
- Documentation on {ref}`how to add tool supports to a model plugin <advanced-model-plugins-tools>`. [#1000](https://github.com/simonw/llm/issues/1000)
- Added a {ref}`prominent warning <tools-warning>` about the risk of prompt injection when using tools. [#1097](https://github.com/simonw/llm/issues/1097)
- Switched to using monotonic ULIDs for the response IDs in the logs, fixing some intermittent test failures. [#1099](https://github.com/simonw/llm/issues/1099)
- New `tool_instances` table records details of Toolbox instances created while executing a prompt. [#1089](https://github.com/simonw/llm/issues/1089)
- `llm.get_key()` is now a {ref}`documented utility function <plugin-utilities-get-key>`. [#1094](https://github.com/simonw/llm/issues/1094)

(v0_26_a1)=
## 0.26a1 (2025-05-25)

Hopefully the last alpha before a stable release that includes tool support.

### Features

*   **Plugin-provided tools can now be grouped into "Toolboxes".**
    *   Toolboxes (`llm.Toolbox` classes) allow plugins to expose multiple related tools that share state or configuration (e.g., a `Memory` tool or `Filesystem` tool). ([#1059](https://github.com/simonw/llm/issues/1059), [#1086](https://github.com/simonw/llm/issues/1086))
*   **Tool support for `llm chat`.**
    *   The `llm chat` command now accepts `--tool` and `--functions` arguments, allowing interactive chat sessions to use tools. ([#1004](https://github.com/simonw/llm/issues/1004), [#1062](https://github.com/simonw/llm/issues/1062))
*   **Tools can now execute asynchronously.**
    *   Models that implement `AsyncModel` can now run tools, including tool functions defined as `async def`. ([#1063](https://github.com/simonw/llm/issues/1063))
*   **`llm chat` now supports adding fragments during a session.**
    *   Use the new `!fragment <id>` command while chatting to insert content from a fragment. Initial fragments can also be passed to `llm chat` using `-f` or `--sf`. Thanks, [Dan Turkel](https://github.com/daturkel). ([#1044](https://github.com/simonw/llm/issues/1044), [#1048](https://github.com/simonw/llm/issues/1048))
*   **Filter `llm logs` by tools.**
    *   New `--tool <name>` option to filter logs to show only responses that involved a specific tool (e.g., `--tool simple_eval`).
    *   The `--tools` flag shows all responses that used any tool. ([#1013](https://github.com/simonw/llm/issues/1013), [#1072](https://github.com/simonw/llm/issues/1072))
*   **`llm schemas list` can output JSON.**
    *   Added `--json` and `--nl` (newline-delimited JSON) options to `llm schemas list` for programmatic access to saved schema definitions. ([#1070](https://github.com/simonw/llm/issues/1070))
*   **Filter `llm similar` results by ID prefix.**
    *   The new `--prefix` option for `llm similar` allows searching for similar items only within IDs that start with a specified string (e.g., `llm similar my-collection --prefix 'docs/'`). Thanks, [Dan Turkel](https://github.com/daturkel). ([#1052](https://github.com/simonw/llm/issues/1052))
*   **Control chained tool execution limit.**
    *   New `--chain-limit <N>` (or `--cl`) option for `llm prompt` and `llm chat` to specify the maximum number of consecutive tool calls allowed for a single prompt. Defaults to 5; set to 0 for unlimited. ([#1025](https://github.com/simonw/llm/issues/1025))
*   **`llm plugins --hook <NAME>` option.**
    *   Filter the list of installed plugins to only show those that implement a specific plugin hook. ([#1047](https://github.com/simonw/llm/issues/1047))
* `llm tools list` now shows toolboxes and their methods. ([#1013](https://github.com/simonw/llm/issues/1013))
* `llm prompt` and `llm chat` now automatically re-enable plugin-provided tools when continuing a conversation (`-c` or `--cid`). ([#1020](https://github.com/simonw/llm/issues/1020))
* The `--tools-debug` option now pretty-prints JSON tool results for improved readability. ([#1083](https://github.com/simonw/llm/issues/1083))
* New `LLM_TOOLS_DEBUG` environment variable to permanently enable `--tools-debug`. ([#1045](https://github.com/simonw/llm/issues/1045))
* `llm chat` sessions now correctly respect default model options configured with `llm models set-options`. Thanks, [André Arko](https://github.com/indirect). ([#985](https://github.com/simonw/llm/issues/985))
* New `--pre` option for `llm install` to allow installing pre-release packages. ([#1060](https://github.com/simonw/llm/issues/1060))
* OpenAI models (`gpt-4o`, `gpt-4o-mini`) now explicitly declare support for tools and vision. ([#1037](https://github.com/simonw/llm/issues/1037))
* The `supports_tools` parameter is now supported in `extra-openai-models.yaml`. Thanks, [Mahesh Hegde ](https://github.com/mahesh-hegde). ([#1068](https://github.com/simonw/llm/issues/1068))

### Bug fixes

*   Fixed a bug where the `name` parameter in `register(function, name="name")` was ignored for tool plugins. ([#1032](https://github.com/simonw/llm/issues/1032))
*   Ensure `pathlib.Path` objects are cast to `str` before passing to `click.edit` in `llm templates edit`. Thanks, [Abizer Lokhandwala](https://github.com/abizer). ([#1031](https://github.com/simonw/llm/issues/1031))


(v0_26_a0)=
## 0.26a0 (2025-05-13)

This is the first alpha to introduce {ref}`support for tools<tools>`! Models with tool capability (which includes the default OpenAI model family) can now be granted access to execute Python functions as part of responding to a prompt.

Tools are supported by {ref}`the command-line interface <usage-tools>`:

```bash
llm --functions '
def multiply(x: int, y: int) -> int:
    """Multiply two numbers."""
    return x * y
' 'what is 34234 * 213345'
```
And in {ref}`the Python API <python-api-tools>`, using a new `model.chain()` method for executing multiple prompts in a sequence:
```python
import llm

def multiply(x: int, y: int) -> int:
    """Multiply two numbers."""
    return x * y

model = llm.get_model("gpt-4.1-mini")
response = model.chain(
    "What is 34234 * 213345?",
    tools=[multiply]
)
print(response.text())
```
New tools can also be defined using the {ref}`register_tools() plugin hook <plugin-hooks-register-tools>`. They can then be called by name from the command-line like this:
```bash
llm -T multiply 'What is 34234 * 213345?'
```
Tool support is currently under **active development**. Consult [this milestone](https://github.com/simonw/llm/milestone/12) for the latest status.

(v0_25)=
## 0.25 (2025-05-04)

- New plugin feature: {ref}`plugin-hooks-register-fragment-loaders` plugins can now return a mixture of fragments and attachments. The [llm-video-frames](https://github.com/simonw/llm-video-frames) plugin is the first to take advantage of this mechanism. [#972](https://github.com/simonw/llm/issues/972)
- New OpenAI models: `gpt-4.1`, `gpt-4.1-mini`, `gpt-41-nano`, `o3`, `o4-mini`. [#945](https://github.com/simonw/llm/issues/945), [#965](https://github.com/simonw/llm/issues/965), [#976](https://github.com/simonw/llm/issues/976).
- New environment variables: `LLM_MODEL` and `LLM_EMBEDDING_MODEL` for setting the model to use without needing to specify `-m model_id` every time. [#932](https://github.com/simonw/llm/issues/932)
- New command: `llm fragments loaders`, to list all currently available fragment loader prefixes provided by plugins. [#941](https://github.com/simonw/llm/issues/941)
- `llm fragments` command now shows fragments ordered by the date they were first used. [#973](https://github.com/simonw/llm/issues/973)
- `llm chat` now includes a `!edit` command for editing a prompt using your default terminal text editor. Thanks, [Benedikt Willi](https://github.com/Hopiu). [#969](https://github.com/simonw/llm/pull/969)
- Allow `-t` and `--system` to be used at the same time. [#916](https://github.com/simonw/llm/issues/916)
- Fixed a bug where accessing a model via its alias would fail to respect any default options set for that model. [#968](https://github.com/simonw/llm/issues/968)
- Improved documentation for {ref}`extra-openai-models.yaml <openai-compatible-models>`. Thanks, [Rahim Nathwani](https://github.com/rahimnathwani) and [Dan Guido](https://github.com/dguido). [#950](https://github.com/simonw/llm/pull/950), [#957](https://github.com/simonw/llm/pull/957)
- `llm -c/--continue` now works correctly with the `-d/--database` option. `llm chat` now accepts that `-d/--database` option. Thanks, [Sukhbinder Singh](https://github.com/sukhbinder). [#933](https://github.com/simonw/llm/issues/933)

(v0_25a0)=
## 0.25a0 (2025-04-10)

- `llm models --options` now shows keys and environment variables for models that use API keys. Thanks, [Steve Morin](https://github.com/smorin). [#903](https://github.com/simonw/llm/issues/903)
- Added `py.typed` marker file so LLM can now be used as a dependency in projects that use `mypy` without a warning. [#887](https://github.com/simonw/llm/issues/887)
- `$` characters can now be used in templates by escaping them as `$$`. Thanks, [@guspix](https://github.com/guspix). [#904](https://github.com/simonw/llm/issues/904)
- LLM now uses `pyproject.toml` instead of `setup.py`. [#908](https://github.com/simonw/llm/issues/908)

(v0_24_2)=
## 0.24.2 (2025-04-08)

- Fixed a bug on Windows with the new `llm -t path/to/file.yaml` feature. [#901](https://github.com/simonw/llm/issues/901)

(v0_24_1)=
## 0.24.1 (2025-04-08)

- Templates can now be specified as a path to a file on disk, using `llm -t path/to/file.yaml`. This makes them consistent with how `-f` fragments are loaded. [#897](https://github.com/simonw/llm/issues/897)
- `llm logs backup /tmp/backup.db` command for {ref}`backing up your <logging-backup>` `logs.db` database. [#879](https://github.com/simonw/llm/issues/879)

(v0_24)=
## 0.24 (2025-04-07)

Support for **fragments** to help assemble prompts for long context models. Improved support for **templates** to support attachments and fragments. New plugin hooks for providing custom loaders for both templates and fragments. See [Long context support in LLM 0.24 using fragments and template plugins](https://simonwillison.net/2025/Apr/7/long-context-llm/) for more on this release.

The new [llm-docs](https://github.com/simonw/llm-docs) plugin demonstrates these new features. Install it like this:

```bash
llm install llm-docs
```
Now you can ask questions of the LLM documentation like this:

```bash
llm -f docs: 'How do I save a new template?'
```
The `docs:` prefix is registered by the plugin. The plugin fetches the LLM documentation for your installed version (from the [docs-for-llms](https://github.com/simonw/docs-for-llms) repository) and uses that as a prompt fragment to help answer your question.

Two more new plugins are [llm-templates-github](https://github.com/simonw/llm-templates-github) and [llm-templates-fabric](https://github.com/simonw/llm-templates-fabric).

`llm-templates-github` lets you share and use templates on GitHub. You can run my [Pelican riding a bicycle](https://simonwillison.net/tags/pelican-riding-a-bicycle/) benchmark against a model like this:

```bash
llm install llm-templates-github
llm -t gh:simonw/pelican-svg -m o3-mini
```
This executes [this pelican-svg.yaml](https://github.com/simonw/llm-templates/blob/main/pelican-svg.yaml) template stored in my [simonw/llm-templates](https://github.com/simonw/llm-templates) repository, using a new repository naming convention.

To share your own templates, create a repository on GitHub under your user account called `llm-templates` and start saving `.yaml` files to it.

[llm-templates-fabric](https://github.com/simonw/llm-templates-fabric) provides a similar mechanism for loading templates from  Daniel Miessler's [fabric collection](https://github.com/danielmiessler/fabric):

```bash
llm install llm-templates-fabric
curl https://simonwillison.net/2025/Apr/6/only-miffy/ | \
  llm -t f:extract_main_idea
```

Major new features:

- New {ref}`fragments feature <fragments>`. Fragments can be used to assemble long prompts from multiple existing pieces - URLs, file paths or previously used fragments. These will be stored de-duplicated in the database avoiding wasting space storing multiple long context pieces. Example usage: `llm -f https://llm.datasette.io/robots.txt 'explain this file'`. [#617](https://github.com/simonw/llm/issues/617)
- The `llm logs` file now accepts `-f` fragment references too, and will show just logged prompts that used those fragments.
- {ref}`register_template_loaders() plugin hook <plugin-hooks-register-template-loaders>` allowing plugins to register new `prefix:value` custom template loaders. [#809](https://github.com/simonw/llm/issues/809)
- {ref}`register_fragment_loaders() plugin hook <plugin-hooks-register-fragment-loaders>` allowing plugins to register new `prefix:value` custom fragment loaders. [#886](https://github.com/simonw/llm/issues/886)
- {ref}`llm fragments <fragments-browsing>` family of commands for browsing fragments that have been previously logged to the database.
- The new [llm-openai plugin](https://github.com/simonw/llm-openai-plugin) provides support for **o1-pro** (which is not supported by the OpenAI mechanism used by LLM core). Future OpenAI features will migrate to this plugin instead of LLM core itself.

Improvements to templates:

- `llm -t $URL` option can now take a URL to a YAML template. [#856](https://github.com/simonw/llm/issues/856)
- Templates can now store default model options. [#845](https://github.com/simonw/llm/issues/845)
- Executing a template that does not use the `$input` variable no longer blocks LLM waiting for input, so prompt templates can now be used to try different models using `llm -t pelican-svg -m model_id`. [#835](https://github.com/simonw/llm/issues/835)
- `llm templates` command no longer crashes if one of the listed template files contains invalid YAML. [#880](https://github.com/simonw/llm/issues/880)
- Attachments can now be stored in templates. [#826](https://github.com/simonw/llm/issues/826)

Other changes:

- New {ref}`llm models options <usage-executing-default-options>` family of commands for setting default options for particular models. [#829](https://github.com/simonw/llm/issues/829)
- `llm logs list`, `llm schemas list` and `llm schemas show` all now take a `-d/--database` option with an optional path to a SQLite database. They used to take `-p/--path` but that was inconsistent with other commands. `-p/--path` still works but is excluded from `--help` and will be removed in a future LLM release. [#857](https://github.com/simonw/llm/issues/857)
- `llm logs -e/--expand` option for expanding fragments. [#881](https://github.com/simonw/llm/issues/881)
- `llm prompt -d path-to-sqlite.db` option can now be used to write logs to a custom SQLite database. [#858](https://github.com/simonw/llm/issues/858)
- `llm similar -p/--plain` option providing more human-readable output than the default JSON. [#853](https://github.com/simonw/llm/issues/853)
- `llm logs -s/--short` now truncates to include the end of the prompt too. Thanks, [Sukhbinder Singh](https://github.com/sukhbinder). [#759](https://github.com/simonw/llm/issues/759)
- Set the `LLM_RAISE_ERRORS=1` environment variable to raise errors during prompts rather than suppressing them, which means you can run `python -i -m llm 'prompt'` and then drop into a debugger on errors with `import pdb; pdb.pm()`. [#817](https://github.com/simonw/llm/issues/817)
- Improved [--help output](https://llm.datasette.io/en/stable/help.html#llm-embed-multi-help) for `llm embed-multi`. [#824](https://github.com/simonw/llm/issues/824)
- `llm models -m X` option which can be passed multiple times with model IDs to see the details of just those models. [#825](https://github.com/simonw/llm/issues/825)
- OpenAI models now accept PDF attachments. [#834](https://github.com/simonw/llm/issues/834)
- `llm prompt -q gpt -q 4o` option - pass `-q searchterm` one or more times to execute a prompt against the first model that matches all of those strings - useful for if you can't remember the full model ID. [#841](https://github.com/simonw/llm/issues/841)
- {ref}`OpenAI compatible models <openai-compatible-models>` configured using `extra-openai-models.yaml` now support `supports_schema: true`, `vision: true` and `audio: true` options. Thanks [@adaitche](https://github.com/adaitche) and [@giuli007](https://github.com/giuli007). [#819](https://github.com/simonw/llm/pull/819), [#843](https://github.com/simonw/llm/pull/843)


(v0_24a1)=
## 0.24a1 (2025-04-06)

- New Fragments feature. [#617](https://github.com/simonw/llm/issues/617)
- `register_fragment_loaders()` plugin hook. [#809](https://github.com/simonw/llm/issues/886)

(v0_24a0)=
## 0.24a0 (2025-02-28)

- Alpha release with experimental `register_template_loaders()` plugin hook. [#809](https://github.com/simonw/llm/issues/809)

(v0_23)=
## 0.23 (2025-02-28)

Support for **schemas**, for getting supported models to output JSON that matches a specified JSON schema. See also [Structured data extraction from unstructured content using LLM schemas](https://simonwillison.net/2025/Feb/28/llm-schemas/) for background on this feature. [#776](https://github.com/simonw/llm/issues/776)

- New `llm prompt --schema '{JSON schema goes here}` option for specifying a schema that should be used for the output from the model. The {ref}`schemas documentation <schemas>` has more details and a tutorial.
- Schemas can also be defined using a {ref}`concise schema specification <schemas-dsl>`, for example `llm prompt --schema 'name, bio, age int'`. [#790](https://github.com/simonw/llm/issues/790)
- Schemas can also be specified by passing a filename and through {ref}`several other methods <schemas-specify>`. [#780](https://github.com/simonw/llm/issues/780)
- New {ref}`llm schemas family of commands <help-schemas>`: `llm schemas list`, `llm schemas show`, and `llm schemas dsl` for debugging the new concise schema language. [#781](https://github.com/simonw/llm/issues/781)
- Schemas can now be saved to templates using `llm --schema X --save template-name` or through modifying the {ref}`template YAML <prompt-templates-yaml>`. [#778](https://github.com/simonw/llm/issues/778)
- The {ref}`llm logs <logging>` command now has new options for extracting data collected using schemas: `--data`, `--data-key`, `--data-array`, `--data-ids`. [#782](https://github.com/simonw/llm/issues/782)
- New `llm logs --id-gt X` and `--id-gte X` options. [#801](https://github.com/simonw/llm/issues/801)
- New `llm models --schemas` option for listing models that support schemas. [#797](https://github.com/simonw/llm/issues/797)
- `model.prompt(..., schema={...})` parameter for specifying a schema from Python. This accepts either a dictionary JSON schema definition or a Pydantic `BaseModel` subclass, see {ref}`schemas in the Python API docs <python-api-schemas>`.
- The default OpenAI plugin now enables schemas across all supported models. Run `llm models --schemas` for a list of these.
- The [llm-anthropic](https://github.com/simonw/llm-anthropic) and [llm-gemini](https://github.com/simonw/llm-gemini) plugins have been upgraded to add schema support for those models. Here's documentation on how to {ref}`add schema support to a model plugin <advanced-model-plugins-schemas>`.

Other smaller changes:

- [GPT-4.5 preview](https://openai.com/index/introducing-gpt-4-5/) is now a supported model: `llm -m gpt-4.5 'a joke about a pelican and a wolf'` [#795](https://github.com/simonw/llm/issues/795)
- The prompt string is now optional when calling `model.prompt()` from the Python API, so `model.prompt(attachments=llm.Attachment(url=url)))` now works. [#784](https://github.com/simonw/llm/issues/784)
- `extra-openai-models.yaml` now supports a `reasoning: true` option. Thanks, [Kasper Primdal Lauritzen](https://github.com/KPLauritzen). [#766](https://github.com/simonw/llm/pull/766)
- LLM now depends on Pydantic v2 or higher. Pydantic v1 is no longer supported. [#520](https://github.com/simonw/llm/issues/520)


(v0_22)=
## 0.22 (2025-02-16)

See also [LLM 0.22, the annotated release notes](https://simonwillison.net/2025/Feb/17/llm/).

- Plugins that provide models that use API keys can now subclass the new `llm.KeyModel` and `llm.AsyncKeyModel` classes. This results in the API key being passed as a new `key` parameter to their `.execute()` methods, and means that Python users can pass a key as the `model.prompt(..., key=)` - see {ref}`Passing an API key <python-api-models-api-keys>`. Plugin developers should consult the new documentation on writing {ref}`Models that accept API keys <advanced-model-plugins-api-keys>`. [#744](https://github.com/simonw/llm/issues/744)
- New OpenAI model: `chatgpt-4o-latest`. This model ID accesses the current model being used to power ChatGPT, which can change without warning. [#752](https://github.com/simonw/llm/issues/752)
- New `llm logs -s/--short` flag, which returns a greatly shortened version of the matching log entries in YAML format with a truncated prompt and without including the response. [#737](https://github.com/simonw/llm/issues/737)
- Both `llm models` and `llm embed-models` now take multiple `-q` search fragments. You can now search for all models matching "gemini" and "exp" using `llm models -q gemini -q exp`. [#748](https://github.com/simonw/llm/issues/748)
- New `llm embed-multi --prepend X` option for prepending a string to each value before it is embedded - useful for models such as [nomic-embed-text-v2-moe](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe) that require passages to start with a string like `"search_document: "`. [#745](https://github.com/simonw/llm/issues/745)
- The `response.json()` and `response.usage()` methods are {ref}`now documented <python-api-underlying-json>`.
- Fixed a bug where conversations that were loaded from the database could not be continued using `asyncio` prompts. [#742](https://github.com/simonw/llm/issues/742)
- New plugin for macOS users: [llm-mlx](https://github.com/simonw/llm-mlx), which provides [extremely high performance access](https://simonwillison.net/2025/Feb/15/llm-mlx/) to a wide range of local models using Apple's MLX framework.
- The `llm-claude-3` plugin has been renamed to [llm-anthropic](https://github.com/simonw/llm-anthropic).

(v0_21)=
## 0.21 (2025-01-31)

- New model: `o3-mini`. [#728](https://github.com/simonw/llm/issues/728)
- The `o3-mini` and `o1` models now support a `reasoning_effort` option which can be set to `low`, `medium` or `high`.
- `llm prompt` and `llm logs` now have a `--xl/--extract-last` option for extracting the last fenced code block in the response - a complement to the existing `--x/--extract` option. [#717](https://github.com/simonw/llm/issues/717)

(v0_20)=
## 0.20 (2025-01-22)

- New model, `o1`. This model does not yet support streaming. [#676](https://github.com/simonw/llm/issues/676)
- `o1-preview` and `o1-mini` models now support streaming.
- New models, `gpt-4o-audio-preview` and `gpt-4o-mini-audio-preview`. [#677](https://github.com/simonw/llm/issues/677)
- `llm prompt -x/--extract` option, which returns just the content of the first fenced code block in the response. Try `llm prompt -x 'Python function to reverse a string'`. [#681](https://github.com/simonw/llm/issues/681)
  - Creating a template using `llm ... --save x` now supports the `-x/--extract` option, which is saved to the template. YAML templates can set this option using `extract: true`.
  - New `llm logs -x/--extract` option extracts the first fenced code block from matching logged responses.
- New `llm models -q 'search'` option returning models that case-insensitively match the search query. [#700](https://github.com/simonw/llm/issues/700)
- Installation documentation now also includes `uv`. Thanks, [Ariel Marcus](https://github.com/ajmarcus). [#690](https://github.com/simonw/llm/pull/690) and [#702](https://github.com/simonw/llm/issues/702)
- `llm models` command now shows the current default model at the bottom of the listing. Thanks, [Amjith Ramanujam](https://github.com/amjith). [#688](https://github.com/simonw/llm/pull/688)
- {ref}`Plugin directory <plugin-directory>` now includes `llm-venice`, `llm-bedrock`, `llm-deepseek` and `llm-cmd-comp`.
- Fixed bug where some dependency version combinations could cause a `Client.__init__() got an unexpected keyword argument 'proxies'` error. [#709](https://github.com/simonw/llm/issues/709)
- OpenAI embedding models are now available using their full names of `text-embedding-ada-002`, `text-embedding-3-small` and `text-embedding-3-large` - the previous names are still supported as aliases. Thanks, [web-sst](https://github.com/web-sst). [#654](https://github.com/simonw/llm/pull/654)

(v0_19_1)=
## 0.19.1 (2024-12-05)

- FIxed bug where `llm.get_models()` and `llm.get_async_models()` returned the same model multiple times. [#667](https://github.com/simonw/llm/issues/667)

(v0_19)=
## 0.19 (2024-12-01)

- Tokens used by a response are now logged to new `input_tokens` and `output_tokens` integer columns and a `token_details` JSON string column, for the default OpenAI models and models from other plugins that {ref}`implement this feature <advanced-model-plugins-usage>`. [#610](https://github.com/simonw/llm/issues/610)
- `llm prompt` now takes a `-u/--usage` flag to display token usage at the end of the response.
- `llm logs -u/--usage` shows token usage information for logged responses.
- `llm prompt ... --async` responses are now logged to the database. [#641](https://github.com/simonw/llm/issues/641)
- `llm.get_models()` and `llm.get_async_models()` functions, {ref}`documented here <python-api-listing-models>`. [#640](https://github.com/simonw/llm/issues/640)
- `response.usage()` and async response `await response.usage()` methods, returning a `Usage(input=2, output=1, details=None)` dataclass. [#644](https://github.com/simonw/llm/issues/644)
- `response.on_done(callback)` and `await response.on_done(callback)` methods for specifying a callback to be executed when a response has completed, {ref}`documented here <python-api-response-on-done>`. [#653](https://github.com/simonw/llm/issues/653)
- Fix for bug running `llm chat` on Windows 11. Thanks, [Sukhbinder Singh](https://github.com/sukhbinder). [#495](https://github.com/simonw/llm/issues/495)

(v0_19a2)=
## 0.19a2 (2024-11-20)

- `llm.get_models()` and `llm.get_async_models()` functions, {ref}`documented here <python-api-listing-models>`. [#640](https://github.com/simonw/llm/issues/640)

(v0_19a1)=
## 0.19a1 (2024-11-19)

- `response.usage()` and async response `await response.usage()` methods, returning a `Usage(input=2, output=1, details=None)` dataclass. [#644](https://github.com/simonw/llm/issues/644)

(v0_19a0)=
## 0.19a0 (2024-11-19)

- Tokens used by a response are now logged to new `input_tokens` and `output_tokens` integer columns and a `token_details` JSON string column, for the default OpenAI models and models from other plugins that {ref}`implement this feature <advanced-model-plugins-usage>`. [#610](https://github.com/simonw/llm/issues/610)
- `llm prompt` now takes a `-u/--usage` flag to display token usage at the end of the response.
- `llm logs -u/--usage` shows token usage information for logged responses.
- `llm prompt ... --async` responses are now logged to the database. [#641](https://github.com/simonw/llm/issues/641)

(v0_18)=
## 0.18 (2024-11-17)

- Initial support for async models. Plugins can now provide an `AsyncModel` subclass that can be accessed in the Python API using the new `llm.get_async_model(model_id)` method. See {ref}`async models in the Python API docs<python-api-async>` and {ref}`implementing async models in plugins <advanced-model-plugins-async>`. [#507](https://github.com/simonw/llm/issues/507)
- OpenAI models all now include async models, so function calls such as `llm.get_async_model("gpt-4o-mini")` will return an async model.
- `gpt-4o-audio-preview` model can be used to send audio attachments to the GPT-4o audio model. [#608](https://github.com/simonw/llm/issues/608)
- Attachments can now be sent without requiring a prompt. [#611](https://github.com/simonw/llm/issues/611)
- `llm models --options` now includes information on whether a model supports attachments. [#612](https://github.com/simonw/llm/issues/612)
- `llm models --async` shows available async models.
- Custom OpenAI-compatible models can now be marked as `can_stream: false` in the YAML if they do not support streaming. Thanks, [Chris Mungall](https://github.com/cmungall). [#600](https://github.com/simonw/llm/pull/600)
- Fixed bug where OpenAI usage data was incorrectly serialized to JSON. [#614](https://github.com/simonw/llm/issues/614)
- Standardized on `audio/wav` MIME type for audio attachments rather than `audio/wave`. [#603](https://github.com/simonw/llm/issues/603)

(v0_18a1)=
## 0.18a1 (2024-11-14)

- Fixed bug where conversations did not work for async OpenAI models. [#632](https://github.com/simonw/llm/issues/632)
- `__repr__` methods for `Response` and `AsyncResponse`.

(v0_18a0)=
## 0.18a0 (2024-11-13)

Alpha support for **async models**. [#507](https://github.com/simonw/llm/issues/507)

Multiple [smaller changes](https://github.com/simonw/llm/compare/0.17.1...0.18a0).

(v0_17)=
## 0.17 (2024-10-29)

Support for **attachments**, allowing multi-modal models to accept images, audio, video and other formats. [#578](https://github.com/simonw/llm/issues/578)

The default OpenAI `gpt-4o` and `gpt-4o-mini` models can both now be prompted with JPEG, GIF, PNG and WEBP images.

Attachments {ref}`in the CLI <usage-attachments>` can be URLs:

```bash
llm -m gpt-4o "describe this image" \
  -a https://static.simonwillison.net/static/2024/pelicans.jpg
```
Or file paths:
```bash
llm -m gpt-4o-mini "extract text" -a image1.jpg -a image2.jpg
```
Or binary data, which may need to use `--attachment-type` to specify the MIME type:
```bash
cat image | llm -m gpt-4o-mini "extract text" --attachment-type - image/jpeg
```

Attachments are also available {ref}`in the Python API <python-api-attachments>`:

```python
model = llm.get_model("gpt-4o-mini")
response = model.prompt(
    "Describe these images",
    attachments=[
        llm.Attachment(path="pelican.jpg"),
        llm.Attachment(url="https://static.simonwillison.net/static/2024/pelicans.jpg"),
    ]
)
```
Plugins that provide alternative models can support attachments, see {ref}`advanced-model-plugins-attachments` for details.

The latest **[llm-claude-3](https://github.com/simonw/llm-claude-3)** plugin now supports attachments for Anthropic's Claude 3 and 3.5 models. The **[llm-gemini](https://github.com/simonw/llm-gemini)** plugin supports attachments for Google's Gemini 1.5 models.

Also in this release: OpenAI models now record their `"usage"` data in the database even when the response was streamed. These records can be viewed using `llm logs --json`. [#591](https://github.com/simonw/llm/issues/591)

(v0_17a0)=
## 0.17a0 (2024-10-28)

Alpha support for **attachments**. [#578](https://github.com/simonw/llm/issues/578)

(v0_16)=
## 0.16 (2024-09-12)

- OpenAI models now use the internal `self.get_key()` mechanism, which means they can be used from Python code in a way that will pick up keys that have been configured using `llm keys set` or the `OPENAI_API_KEY` environment variable. [#552](https://github.com/simonw/llm/issues/552). This code now works correctly:
    ```python
    import llm
    print(llm.get_model("gpt-4o-mini").prompt("hi"))
    ```
- New documented API methods: `llm.get_default_model()`, `llm.set_default_model(alias)`, `llm.get_default_embedding_model(alias)`, `llm.set_default_embedding_model()`. [#553](https://github.com/simonw/llm/issues/553)
- Support for OpenAI's new [o1 family](https://openai.com/o1/) of preview models, `llm -m o1-preview "prompt"` and `llm -m o1-mini "prompt"`. These models are currently only available to [tier 5](https://platform.openai.com/docs/guides/rate-limits/usage-tiers?context=tier-five) OpenAI API users, though this may change in the future. [#570](https://github.com/simonw/llm/issues/570)

(v0_15)=
## 0.15 (2024-07-18)

- Support for OpenAI's [new GPT-4o mini](https://openai.com/index/gpt-4o-mini-advancing-cost-efficient-intelligence/) model: `llm -m gpt-4o-mini 'rave about pelicans in French'` [#536](https://github.com/simonw/llm/issues/536)
- `gpt-4o-mini` is now the default model if you do not {ref}`specify your own default <setup-default-model>`, replacing GPT-3.5 Turbo. GPT-4o mini is both cheaper and better than GPT-3.5 Turbo.
- Fixed a bug where `llm logs -q 'flourish' -m haiku` could not combine both the `-q` search query and the `-m` model specifier. [#515](https://github.com/simonw/llm/issues/515)

(v0_14)=
## 0.14 (2024-05-13)

- Support for OpenAI's [new GPT-4o](https://openai.com/index/hello-gpt-4o/) model: `llm -m gpt-4o 'say hi in Spanish'` [#490](https://github.com/simonw/llm/issues/490)
- The `gpt-4-turbo` alias is now a model ID, which indicates the latest version of OpenAI's GPT-4 Turbo text and image model. Your existing `logs.db` database may contain records under the previous model ID of `gpt-4-turbo-preview`. [#493](https://github.com/simonw/llm/issues/493)
- New `llm logs -r/--response` option for outputting just the last captured response, without wrapping it in Markdown and accompanying it with the prompt. [#431](https://github.com/simonw/llm/issues/431)
- Nine new {ref}`plugins <plugin-directory>` since version 0.13:
  - **[llm-claude-3](https://github.com/simonw/llm-claude-3)** supporting Anthropic's [Claude 3 family](https://www.anthropic.com/news/claude-3-family) of models.
  - **[llm-command-r](https://github.com/simonw/llm-command-r)** supporting Cohere's Command R and [Command R Plus](https://txt.cohere.com/command-r-plus-microsoft-azure/) API models.
  - **[llm-reka](https://github.com/simonw/llm-reka)** supports the [Reka](https://www.reka.ai/) family of models via their API.
  - **[llm-perplexity](https://github.com/hex/llm-perplexity)** by Alexandru Geana supporting the [Perplexity Labs](https://docs.perplexity.ai/) API models, including `llama-3-sonar-large-32k-online` which can search for things online and `llama-3-70b-instruct`.
  - **[llm-groq](https://github.com/angerman/llm-groq)** by Moritz Angermann providing access to fast models hosted by [Groq](https://console.groq.com/docs/models).
  - **[llm-fireworks](https://github.com/simonw/llm-fireworks)** supporting models hosted by [Fireworks AI](https://fireworks.ai/).
  - **[llm-together](https://github.com/wearedevx/llm-together)** adds support for the [Together AI](https://www.together.ai/) extensive family of hosted openly licensed models.
  - **[llm-embed-onnx](https://github.com/simonw/llm-embed-onnx)** provides seven embedding models that can be executed using the ONNX model framework.
  - **[llm-cmd](https://github.com/simonw/llm-cmd)** accepts a prompt for a shell command, runs that prompt and populates the result in your shell so you can review it, edit it and then hit `<enter>` to execute or `ctrl+c` to cancel, see [this post for details](https://simonwillison.net/2024/Mar/26/llm-cmd/).

(v0_13_1)=
## 0.13.1 (2024-01-26)

- Fix for `No module named 'readline'` error on Windows. [#407](https://github.com/simonw/llm/issues/407)

(v0_13)=
## 0.13 (2024-01-26)

See also [LLM 0.13: The annotated release notes](https://simonwillison.net/2024/Jan/26/llm/).

- Added support for new OpenAI embedding models: `3-small` and `3-large` and three variants of those with different dimension sizes, 
`3-small-512`, `3-large-256` and `3-large-1024`. See {ref}`OpenAI embedding models <openai-models-embedding>` for details. [#394](https://github.com/simonw/llm/issues/394)
- The default `gpt-4-turbo` model alias now points to `gpt-4-turbo-preview`, which uses the most recent OpenAI GPT-4 turbo model (currently `gpt-4-0125-preview`). [#396](https://github.com/simonw/llm/issues/396)
- New OpenAI model aliases `gpt-4-1106-preview` and `gpt-4-0125-preview`.
- OpenAI models now support a `-o json_object 1` option which will cause their output to be returned as a valid JSON object. [#373](https://github.com/simonw/llm/issues/373)
- New {ref}`plugins <plugin-directory>` since the last release include [llm-mistral](https://github.com/simonw/llm-mistral), [llm-gemini](https://github.com/simonw/llm-gemini), [llm-ollama](https://github.com/taketwo/llm-ollama) and [llm-bedrock-meta](https://github.com/flabat/llm-bedrock-meta).
- The `keys.json` file for storing API keys is now created with `600` file permissions. [#351](https://github.com/simonw/llm/issues/351)
- Documented {ref}`a pattern <homebrew-warning>` for installing plugins that depend on PyTorch using the Homebrew version of LLM, despite Homebrew using Python 3.12 when PyTorch have not yet released a stable package for that Python version. [#397](https://github.com/simonw/llm/issues/397)
- Underlying OpenAI Python library has been upgraded to `>1.0`. It is possible this could cause compatibility issues with LLM plugins that also depend on that library. [#325](https://github.com/simonw/llm/issues/325)
- Arrow keys now work inside the `llm chat` command. [#376](https://github.com/simonw/llm/issues/376)
- `LLM_OPENAI_SHOW_RESPONSES=1` environment variable now outputs much more detailed information about the HTTP request and response made to OpenAI (and OpenAI-compatible) APIs. [#404](https://github.com/simonw/llm/issues/404)
- Dropped support for Python 3.7.

(v0_12)=
## 0.12 (2023-11-06)

- Support for the [new GPT-4 Turbo model](https://openai.com/blog/new-models-and-developer-products-announced-at-devday) from OpenAI. Try it using `llm chat -m gpt-4-turbo` or `llm chat -m 4t`. [#323](https://github.com/simonw/llm/issues/323)
- New `-o seed 1` option for OpenAI models which sets a seed that can attempt to evaluate the prompt deterministically. [#324](https://github.com/simonw/llm/issues/324)

(v0_11_2)=
## 0.11.2 (2023-11-06)

- Pin to version of OpenAI Python library prior to 1.0 to avoid breaking. [#327](https://github.com/simonw/llm/issues/327)

(v0_11_1)=
## 0.11.1 (2023-10-31)

- Fixed a bug where `llm embed -c "text"` did not correctly pick up the configured {ref}`default embedding model <embeddings-cli-embed-models-default>`. [#317](https://github.com/simonw/llm/issues/317)
- New plugins: [llm-python](https://github.com/simonw/llm-python), [llm-bedrock-anthropic](https://github.com/sblakey/llm-bedrock-anthropic) and [llm-embed-jina](https://github.com/simonw/llm-embed-jina) (described in [Execute Jina embeddings with a CLI using llm-embed-jina](https://simonwillison.net/2023/Oct/26/llm-embed-jina/)).
- [llm-gpt4all](https://github.com/simonw/llm-gpt4all) now uses the new GGUF model format. [simonw/llm-gpt4all#16](https://github.com/simonw/llm-gpt4all/issues/16)

(v0_11)=
## 0.11 (2023-09-18)

LLM now supports the new OpenAI `gpt-3.5-turbo-instruct` model, and OpenAI completion (as opposed to chat completion) models in general. [#284](https://github.com/simonw/llm/issues/284)

```bash
llm -m gpt-3.5-turbo-instruct 'Reasons to tame a wild beaver:'
```
OpenAI completion models like this support a `-o logprobs 3` option, which accepts a number between 1 and 5 and will include the log probabilities (for each produced token, what were the top 3 options considered by the model) in the logged response.

```bash
llm -m gpt-3.5-turbo-instruct 'Say hello succinctly' -o logprobs 3
```
You can then view the `logprobs` that were recorded in the SQLite logs database like this:
```bash
sqlite-utils "$(llm logs path)" \
  'select * from responses order by id desc limit 1' | \
  jq '.[0].response_json' -r | jq
```
Truncated output looks like this:
```
  [
    {
      "text": "Hi",
      "top_logprobs": [
        {
          "Hi": -0.13706253,
          "Hello": -2.3714375,
          "Hey": -3.3714373
        }
      ]
    },
    {
      "text": " there",
      "top_logprobs": [
        {
          " there": -0.96057636,
          "!\"": -0.5855763,
          ".\"": -3.2574513
        }
      ]
    }
  ]
```
Also in this release:

- The `llm.user_dir()` function, used by plugins, now ensures the directory exists before returning it. [#275](https://github.com/simonw/llm/issues/275)
- New `LLM_OPENAI_SHOW_RESPONSES=1` environment variable for displaying the full HTTP response returned by OpenAI compatible APIs. [#286](https://github.com/simonw/llm/issues/286)
- The `llm embed-multi` command now has a `--batch-size X` option for setting the batch size to use when processing embeddings - useful if you have limited memory available. [#273](https://github.com/simonw/llm/issues/273)
- The `collection.embed_multi()` method also now accepts an optional `batch_size=int` argument.
- Fixed two bugs with `llm embed-multi --files` relating to handling of directories. Thanks, [ealvar3z](https://github.com/ealvar3z). [#274](https://github.com/simonw/llm/issues/274), [#280](https://github.com/simonw/llm/issues/280)

(v0_10)=
## 0.10 (2023-09-12)

The two major features in this release are the **{ref}`llm chat command <usage-chat>`** and support for **embedding binary data**.

See [Build an image search engine with llm-clip, chat with models with llm chat](https://simonwillison.net/2023/Sep/12/llm-clip-and-chat/) for more background on these features.

### llm chat

The new `llm chat` command starts an ongoing chat conversation with a model in your terminal. It works with all models supported by LLM and its {ref}`plugins <plugins>`, including locally installed models such as Llama 2. [#231](https://github.com/simonw/llm/issues/231)

This offers a big performance boost for local models, since they don't need to be freshly loaded into memory for each prompt.

Here's an example chat with Llama 2 13B, provided by the [llm-mlc](https://github.com/simonw/llm-mlc) plugin.

```bash
llm chat -m mlc-chat-Llama-2-13b-chat-hf-q4f16_1
```
This starts a chat session:
```
Type 'exit' or 'quit' to exit
Type '!multi' to enter multiple lines, then '!end' to finish
Type '!edit' to open your default editor and modify the prompt.
> Who are you?
Hello! I'm just an AI, here to assist you with any questions you may have.
My name is LLaMA, and I'm a large language model trained to provide helpful
and informative responses to a wide range of questions and topics. I'm here
to help you find the information you need, while ensuring a safe and
respectful conversation. Please feel free to ask me anything, and I'll do my
best to provide a helpful and accurate response.
> Tell me a joke about otters
Sure, here's a joke about otters:

Why did the otter go to the party?

Because he heard it was a "whale" of a time!

(Get it? Whale, like a big sea mammal, but also a "wild" or "fun" time.
Otters are known for their playful and social nature, so it's a lighthearted
and silly joke.)

I hope that brought a smile to your face! Do you have any other questions or
topics you'd like to discuss?
> exit
```
Chat sessions are {ref}`logged to SQLite <logging>` - use `llm logs` to view them. They can accept system prompts, templates and model options - consult {ref}`the chat documentation <usage-chat>` for details.

### Binary embedding support

LLM's {ref}`embeddings feature <embeddings>` has been expanded to provide support for embedding binary data, in addition to text. [#254](https://github.com/simonw/llm/pull/254)

This enables models like [CLIP](https://openai.com/research/clip), supported by the new **[llm-clip](https://github.com/simonw/llm-clip)** plugin.

CLIP is a multi-modal embedding model which can embed images and text into the same vector space. This means you can use it to create an embedding index of photos, and then search for the embedding vector for "a happy dog" and get back images that are semantically closest to that string.

To create embeddings for every JPEG in a directory stored in a `photos` collection, run:

```bash
llm install llm-clip
llm embed-multi photos --files photos/ '*.jpg' --binary -m clip
```
Now you can search for photos of raccoons using:
```
llm similar photos -c 'raccoon'
```
This spits out a list of images, ranked by how similar they are to the string "raccoon":
```
{"id": "IMG_4801.jpeg", "score": 0.28125139257127457, "content": null, "metadata": null}
{"id": "IMG_4656.jpeg", "score": 0.26626441704164294, "content": null, "metadata": null}
{"id": "IMG_2944.jpeg", "score": 0.2647445926996852, "content": null, "metadata": null}
...
```

### Also in this release

- The {ref}`LLM_LOAD_PLUGINS environment variable <llm-load-plugins>` can be used to control which plugins are loaded when `llm` starts running. [#256](https://github.com/simonw/llm/issues/256)
- The `llm plugins --all` option includes builtin plugins in the list of plugins. [#259](https://github.com/simonw/llm/issues/259)
- The `llm embed-db` family of commands has been renamed to `llm collections`. [#229](https://github.com/simonw/llm/issues/229)
- `llm embed-multi --files` now has an `--encoding` option and defaults to falling back to `latin-1` if a file cannot be processed as `utf-8`. [#225](https://github.com/simonw/llm/issues/225)

(v0_10_a1)=
## 0.10a1 (2023-09-11)

- Support for embedding binary data. [#254](https://github.com/simonw/llm/pull/254)
- `llm chat` now works for models with API keys. [#247](https://github.com/simonw/llm/issues/247)
- `llm chat -o` for passing options to a model. [#244](https://github.com/simonw/llm/issues/244)
- `llm chat --no-stream` option. [#248](https://github.com/simonw/llm/issues/248)
- `LLM_LOAD_PLUGINS` environment variable. [#256](https://github.com/simonw/llm/issues/256)
- `llm plugins --all` option for including builtin plugins. [#259](https://github.com/simonw/llm/issues/259)
- `llm embed-db` has been renamed to `llm collections`. [#229](https://github.com/simonw/llm/issues/229)
- Fixed bug where `llm embed -c` option was treated as a filepath, not a string. Thanks, [mhalle](https://github.com/mhalle). [#263](https://github.com/simonw/llm/pull/263)

(v0_10_a0)=
## 0.10a0 (2023-09-04)

- New {ref}`llm chat <usage-chat>` command for starting an interactive terminal chat with a model. [#231](https://github.com/simonw/llm/issues/231)
- `llm embed-multi --files` now has an `--encoding` option and defaults to falling back to `latin-1` if a file cannot be processed as `utf-8`. [#225](https://github.com/simonw/llm/issues/225)

(v0_9)=
## 0.9 (2023-09-03)

The big new feature in this release is support for **embeddings**. See [LLM now provides tools for working with embeddings](https://simonwillison.net/2023/Sep/4/llm-embeddings/) for additional details.

{ref}`Embedding models <embeddings>` take a piece of text - a word, sentence, paragraph or even a whole article, and convert that into an array of floating point numbers. [#185](https://github.com/simonw/llm/issues/185)

This embedding vector can be thought of as representing a position in many-dimensional-space, where the distance between two vectors represents how semantically similar they are to each other within the content of a language model.

Embeddings can be used to find **related documents**, and also to implement **semantic search** - where a user can search for a phrase and get back results that are semantically similar to that phrase even if they do not share any exact keywords.

LLM now provides both CLI and Python APIs for working with embeddings. Embedding models are defined by plugins, so you can install additional models using the {ref}`plugins mechanism <installing-plugins>`.

The first two embedding models supported by LLM are:

- OpenAI's [ada-002](https://platform.openai.com/docs/guides/embeddings) embedding model, available via an inexpensive API if you set an OpenAI key using `llm keys set openai`.
- The [sentence-transformers](https://www.sbert.net/) family of models, available via the new [llm-sentence-transformers](https://github.com/simonw/llm-sentence-transformers) plugin.

See {ref}`embeddings-cli` for detailed instructions on working with embeddings using LLM.

The new commands for working with embeddings are:

- **{ref}`llm embed <embeddings-cli-embed>`** - calculate embeddings for content and return them to the console or store them in a SQLite database.
- **{ref}`llm embed-multi <embeddings-cli-embed-multi>`** - run bulk embeddings for multiple strings, using input from a CSV, TSV or JSON file, data from a SQLite database or data found by scanning the filesystem. [#215](https://github.com/simonw/llm/issues/215)
- **{ref}`llm similar <embeddings-cli-similar>`** - run similarity searches against your stored embeddings - starting with a search phrase or finding content related to a previously stored vector. [#190](https://github.com/simonw/llm/issues/190)
- **{ref}`llm embed-models <embeddings-cli-embed-models>`** - list available embedding models.
- `llm embed-db` - commands for inspecting and working with the default embeddings SQLite database.

There's also a new {ref}`llm.Collection <embeddings-python-collections>` class for creating and searching collections of embedding from Python code, and a {ref}`llm.get_embedding_model() <embeddings-python-api>` interface for embedding strings directly. [#191](https://github.com/simonw/llm/issues/191)

(v0_8_1)=
## 0.8.1 (2023-08-31)

- Fixed bug where first prompt would show an error if the `io.datasette.llm` directory had not yet been created. [#193](https://github.com/simonw/llm/issues/193)
- Updated documentation to recommend a different `llm-gpt4all` model since the one we were using is no longer available. [#195](https://github.com/simonw/llm/issues/195)

(v0_8)=
## 0.8 (2023-08-20)

- The output format for `llm logs` has changed. Previously it was JSON - it's now a much more readable Markdown format suitable for pasting into other documents. [#160](https://github.com/simonw/llm/issues/160)
  - The new `llm logs --json` option can be used to get the old JSON format.
  - Pass `llm logs --conversation ID` or `--cid ID` to see the full logs for a specific conversation.
- You can now combine piped input and a prompt in a single command: `cat script.py | llm 'explain this code'`. This works even for models that do not support {ref}`system prompts <usage-system-prompts>`. [#153](https://github.com/simonw/llm/issues/153)
- Additional {ref}`openai-compatible-models` can now be configured with custom HTTP headers. This enables platforms such as [openrouter.ai](https://openrouter.ai/) to be used with LLM, which can provide Claude access even without an Anthropic API key.
- Keys set in `keys.json` are now used in preference to environment variables. [#158](https://github.com/simonw/llm/issues/158)
- The documentation now includes a {ref}`plugin directory <plugin-directory>` listing all available plugins for LLM. [#173](https://github.com/simonw/llm/issues/173)
- New {ref}`related tools <related-tools>` section in the documentation describing `ttok`, `strip-tags` and `symbex`. [#111](https://github.com/simonw/llm/issues/111)
- The `llm models`, `llm aliases` and `llm templates` commands now default to running the same command as `llm models list` and `llm aliases list` and `llm templates list`. [#167](https://github.com/simonw/llm/issues/167)
- New `llm keys` (aka `llm keys list`) command for listing the names of all configured keys. [#174](https://github.com/simonw/llm/issues/174)
- Two new Python API functions, `llm.set_alias(alias, model_id)` and `llm.remove_alias(alias)` can be used to configure aliases from within Python code. [#154](https://github.com/simonw/llm/pull/154)
- LLM is now compatible with both Pydantic 1 and Pydantic 2. This means you can install `llm` as a Python dependency in a project that depends on Pydantic 1 without running into dependency conflicts. Thanks, [Chris Mungall](https://github.com/cmungall). [#147](https://github.com/simonw/llm/pull/147)
- `llm.get_model(model_id)` is now documented as raising `llm.UnknownModelError` if the requested model does not exist. [#155](https://github.com/simonw/llm/issues/155)

(v0_7_1)=
## 0.7.1 (2023-08-19)

- Fixed a bug where some users would see an `AlterError: No such column: log.id` error when attempting to use this tool, after upgrading to the latest [sqlite-utils 3.35 release](https://sqlite-utils.datasette.io/en/stable/changelog.html#v3-35). [#162](https://github.com/simonw/llm/issues/162)

(v0_7)=
## 0.7 (2023-08-12)

The new {ref}`aliases` commands can be used to configure additional aliases for models, for example:

```bash
llm aliases set turbo gpt-3.5-turbo-16k
```
Now you can run the 16,000 token `gpt-3.5-turbo-16k` model like this:

```bash
llm -m turbo 'An epic Greek-style saga about a cheesecake that builds a SQL database from scratch'
```
Use `llm aliases list` to see a list of aliases and `llm aliases remove turbo` to remove one again. [#151](https://github.com/simonw/llm/issues/151)

### Notable new plugins

- **[llm-mlc](https://github.com/simonw/llm-mlc)** can run local models released by the [MLC project](https://mlc.ai/mlc-llm/), including models that can take advantage of the GPU on Apple Silicon M1/M2 devices.
- **[llm-llama-cpp](https://github.com/simonw/llm-llama-cpp)** uses [llama.cpp](https://github.com/ggerganov/llama.cpp) to run models published in the GGML format. See [Run Llama 2 on your own Mac using LLM and Homebrew](https://simonwillison.net/2023/Aug/1/llama-2-mac/) for more details.

### Also in this release

- OpenAI models now have min and max validation on their floating point options. Thanks, Pavel Král. [#115](https://github.com/simonw/llm/issues/115)
- Fix for bug where `llm templates list` raised an error if a template had an empty prompt. Thanks, Sherwin Daganato. [#132](https://github.com/simonw/llm/pull/132)
- Fixed bug in `llm install --editable` option which prevented installation of `.[test]`. [#136](https://github.com/simonw/llm/issues/136)
- `llm install --no-cache-dir` and `--force-reinstall` options. [#146](https://github.com/simonw/llm/issues/146)

(v0_6_1)=
## 0.6.1 (2023-07-24)

- LLM can now be installed directly from Homebrew core: `brew install llm`. [#124](https://github.com/simonw/llm/issues/124)
- Python API documentation now covers {ref}`python-api-system-prompts`.
- Fixed incorrect example in the {ref}`prompt-templates` documentation. Thanks, Jorge Cabello. [#125](https://github.com/simonw/llm/pull/125)

(v0_6)=
## 0.6 (2023-07-18)

- Models hosted on [Replicate](https://replicate.com/) can now be accessed using the [llm-replicate](https://github.com/simonw/llm-replicate) plugin, including the new Llama 2 model from Meta AI. More details here: [Accessing Llama 2 from the command-line with the llm-replicate plugin](https://simonwillison.net/2023/Jul/18/accessing-llama-2/).
- Model providers that expose an API that is compatible with the OpenAPI API format, including self-hosted model servers such as [LocalAI](https://github.com/go-skynet/LocalAI), can now be accessed using {ref}`additional configuration <openai-compatible-models>` for the default OpenAI plugin. [#106](https://github.com/simonw/llm/issues/106)
- OpenAI models that are not yet supported by LLM can also {ref}`be configured <openai-extra-models>` using the new `extra-openai-models.yaml` configuration file. [#107](https://github.com/simonw/llm/issues/107)
- The {ref}`llm logs command <logging-view>` now accepts a `-m model_id` option to filter logs to a specific model. Aliases can be used here in addition to model IDs. [#108](https://github.com/simonw/llm/issues/108)
- Logs now have a SQLite full-text search index against their prompts and responses, and the `llm logs -q SEARCH` option can be used to return logs that match a search term. [#109](https://github.com/simonw/llm/issues/109)

(v0_5)=
## 0.5 (2023-07-12)

LLM now supports **additional language models**, thanks to a new {ref}`plugins mechanism <installing-plugins>` for installing additional models.

Plugins are available for 19 models in addition to the default OpenAI ones:

- [llm-gpt4all](https://github.com/simonw/llm-gpt4all) adds support for 17 models that can download and run on your own device, including Vicuna, Falcon and wizardLM.
- [llm-mpt30b](https://github.com/simonw/llm-mpt30b) adds support for the MPT-30B model, a 19GB download.
- [llm-palm](https://github.com/simonw/llm-palm) adds support for Google's PaLM 2 via the Google API.

A comprehensive tutorial, {ref}`writing a plugin to support a new model <tutorial-model-plugin>` describes how to add new models by building plugins in detail.

### New features

- {ref}`python-api` documentation for using LLM models, including models from plugins, directly from Python. [#75](https://github.com/simonw/llm/issues/75)
- Messages are now logged to the database by default - no need to run the `llm init-db` command any more, which has been removed. Instead, you can toggle this behavior off using `llm logs off` or turn it on again using `llm logs on`. The `llm logs status` command shows the current status of the log database. If logging is turned off, passing `--log` to the `llm prompt` command will cause that prompt to be logged anyway. [#98](https://github.com/simonw/llm/issues/98)
- New database schema for logged messages, with `conversations` and `responses` tables. If you have previously used the old `logs` table it will continue to exist but will no longer be written to. [#91](https://github.com/simonw/llm/issues/91)
- New `-o/--option name value` syntax for setting options for models, such as temperature. Available options differ for different models. [#63](https://github.com/simonw/llm/issues/63)
- `llm models list --options` command for viewing all available model options. [#82](https://github.com/simonw/llm/issues/82)
- `llm "prompt" --save template` option for saving a prompt directly to a template. [#55](https://github.com/simonw/llm/issues/55)
- Prompt templates can now specify {ref}`default values <prompt-default-parameters>` for parameters. Thanks,  Chris Mungall. [#57](https://github.com/simonw/llm/pull/57)
- `llm openai models` command to list all available OpenAI models from their API. [#70](https://github.com/simonw/llm/issues/70)
- `llm models default MODEL_ID` to set a different model as the default to be used when `llm` is run without the `-m/--model` option. [#31](https://github.com/simonw/llm/issues/31)

### Smaller improvements

- `llm -s` is now a shortcut for `llm --system`. [#69](https://github.com/simonw/llm/issues/69)
- `llm -m 4-32k` alias for `gpt-4-32k`.
- `llm install -e directory` command for installing a plugin from a local directory.
- The `LLM_USER_PATH` environment variable now controls the location of the directory in which LLM stores its data. This replaces the old `LLM_KEYS_PATH` and `LLM_LOG_PATH` and `LLM_TEMPLATES_PATH` variables. [#76](https://github.com/simonw/llm/issues/76)
- Documentation covering {ref}`plugin-utilities`.
- Documentation site now uses Plausible for analytics. [#79](https://github.com/simonw/llm/issues/79)

(v0_4_1)=
## 0.4.1 (2023-06-17)

- LLM can now be installed using Homebrew: `brew install simonw/llm/llm`. [#50](https://github.com/simonw/llm/issues/50)
- `llm` is now styled LLM in the documentation. [#45](https://github.com/simonw/llm/issues/45)
- Examples in documentation now include a copy button. [#43](https://github.com/simonw/llm/issues/43)
- `llm templates` command no longer has its display disrupted by newlines. [#42](https://github.com/simonw/llm/issues/42)
- `llm templates` command now includes system prompt, if set. [#44](https://github.com/simonw/llm/issues/44)

(v0_4)=
## 0.4 (2023-06-17)

This release includes some backwards-incompatible changes:

- The `-4` option for GPT-4 is now `-m 4`.
- The `--code` option has been removed.
- The `-s` option has been removed as streaming is now the default. Use `--no-stream` to opt out of streaming.

### Prompt templates

{ref}`prompt-templates` is a new feature that allows prompts to be saved as templates and re-used with different variables.

Templates can be created using the `llm templates edit` command:

```bash
llm templates edit summarize
```
Templates are YAML - the following template defines summarization using a system prompt:

```yaml
system: Summarize this text
```
The template can then be executed like this:
```bash
cat myfile.txt | llm -t summarize
```
Templates can include both system prompts, regular prompts and indicate the model they should use. They can reference variables such as `$input` for content piped to the tool, or other variables that are passed using the new `-p/--param` option.

This example adds a `voice` parameter:

```yaml
system: Summarize this text in the voice of $voice
```
Then to run it (via [strip-tags](https://github.com/simonw/strip-tags) to remove HTML tags from the input):
```bash
curl -s 'https://til.simonwillison.net/macos/imovie-slides-and-audio' | \
  strip-tags -m | llm -t summarize -p voice GlaDOS
```
Example output:

> My previous test subject seemed to have learned something new about iMovie. They exported keynote slides as individual images [...] Quite impressive for a human.

The {ref}`prompt-templates` documentation provides more detailed examples.

### Continue previous chat

You can now use `llm` to continue a previous conversation with the OpenAI chat models (`gpt-3.5-turbo` and `gpt-4`). This will include your previous prompts and responses in the prompt sent to the API, allowing the model to continue within the same context.

Use the new `-c/--continue` option to continue from the previous message thread:

```bash
llm "Pretend to be a witty gerbil, say hi briefly"
```
> Greetings, dear human! I am a clever gerbil, ready to entertain you with my quick wit and endless energy.
```bash
llm "What do you think of snacks?" -c
```
> Oh, how I adore snacks, dear human! Crunchy carrot sticks, sweet apple slices, and chewy yogurt drops are some of my favorite treats. I could nibble on them all day long!

The `-c` option will continue from the most recent logged message.

To continue a different chat, pass an integer ID to the `--chat` option. This should be the ID of a previously logged message. You can find these IDs using the `llm logs` command.

Thanks [Amjith Ramanujam](https://github.com/amjith) for contributing to this feature. [#6](https://github.com/simonw/llm/issues/6)

### New mechanism for storing API keys

API keys for language models such as those by OpenAI can now be saved using the new `llm keys` family of commands.

To set the default key to be used for the OpenAI APIs, run this:

```bash
llm keys set openai
```
Then paste in your API key.

Keys can also be passed using the new `--key` command line option - this can be a full key or the alias of a key that has been previously stored.

See {ref}`api-keys` for more. [#13](https://github.com/simonw/llm/issues/13)

### New location for the logs.db database

The `logs.db` database that stores a history of executed prompts no longer lives at `~/.llm/log.db` - it can now be found in a location that better fits the host operating system, which can be seen using:

```bash
llm logs path
```
On macOS this is `~/Library/Application Support/io.datasette.llm/logs.db`.

To open that database using Datasette, run this:

```bash
datasette "$(llm logs path)"
```
You can upgrade your existing installation by copying your database to the new location like this:
```bash
cp ~/.llm/log.db "$(llm logs path)"
rm -rf ~/.llm # To tidy up the now obsolete directory
```
The database schema has changed, and will be updated automatically the first time you run the command.

That schema is [included in the documentation](https://llm.datasette.io/en/stable/logging.html#sql-schema). [#35](https://github.com/simonw/llm/issues/35)

### Other changes

- New `llm logs --truncate` option (shortcut `-t`) which truncates the displayed prompts to make the log output easier to read. [#16](https://github.com/simonw/llm/issues/16)
- Documentation now spans multiple pages and lives at <https://llm.datasette.io/> [#21](https://github.com/simonw/llm/issues/21)
- Default `llm chatgpt` command has been renamed to `llm prompt`. [#17](https://github.com/simonw/llm/issues/17)
- Removed `--code` option in favour of new prompt templates mechanism. [#24](https://github.com/simonw/llm/issues/24)
- Responses are now streamed by default, if the model supports streaming. The `-s/--stream` option has been removed. A new `--no-stream` option can be used to opt-out of streaming.  [#25](https://github.com/simonw/llm/issues/25)
- The `-4/--gpt4` option has been removed in favour of `-m 4` or `-m gpt4`, using a new mechanism that allows models to have additional short names.
- The new `gpt-3.5-turbo-16k` model with a 16,000 token context length can now also be accessed using `-m chatgpt-16k` or `-m 3.5-16k`. Thanks, Benjamin Kirkbride. [#37](https://github.com/simonw/llm/issues/37)
- Improved display of error messages from OpenAI. [#15](https://github.com/simonw/llm/issues/15)

(v0_3)=
## 0.3 (2023-05-17)

- `llm logs` command for browsing logs of previously executed completions. [#3](https://github.com/simonw/llm/issues/3)
- `llm "Python code to output factorial 10" --code` option which sets a system prompt designed to encourage code to be output without any additional explanatory text. [#5](https://github.com/simonw/llm/issues/5)
- Tool can now accept a prompt piped directly to standard input. [#11](https://github.com/simonw/llm/issues/11)

(v0_2)=
## 0.2 (2023-04-01)

- If a SQLite database exists in `~/.llm/log.db` all prompts and responses are logged to that file. The `llm init-db` command can be used to create this file. [#2](https://github.com/simonw/llm/issues/2)

(v0_1)=
## 0.1 (2023-04-01)

- Initial prototype release. [#1](https://github.com/simonw/llm/issues/1)
