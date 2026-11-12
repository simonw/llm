<!-- [[[cog
# README.md is generated from docs/index.md using sphinx_markdown_builder
import tempfile
import subprocess
from pathlib import Path

readme_markdown = ''

with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    # Run: sphinx-build -M markdown ./docs ./tmpdir
    subprocess.run([
        "sphinx-build",
        "-M", "markdown",
        "./docs",
        str(tmp_path)
    ], check=True)
    index_file = tmp_path / "markdown" / "index.md"
    readme_markdown = index_file.read_text(encoding="utf-8")

cog.out(readme_markdown)
]]] -->
# LLM

[![GitHub repo](https://img.shields.io/badge/github-repo-green)](https://github.com/simonw/llm)
[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/823971286308356157?label=discord)](https://datasette.io/discord-llm)
[![Homebrew](https://img.shields.io/homebrew/installs/dy/llm?color=yellow&label=homebrew&logo=homebrew)](https://formulae.brew.sh/formula/llm)

A CLI tool and Python library for interacting with **OpenAI**, **Anthropic’s Claude**, **Google’s Gemini**, **Qwen**, **Gemma**, **Kimi**, **DeepSeek**, **Mistral**, and dozens of other Large Language Models, both via remote APIs and with models that can be installed and run on your own machine.

Watch **[Language models on the command-line](https://www.youtube.com/watch?v=QUXQNi6jQ30)** on YouTube for a demo or [read the accompanying detailed notes](https://simonwillison.net/2024/Jun/17/cli-language-models/).

With LLM you can:

- [Run prompts from the command-line](https://llm.datasette.io/en/stable/usage.html#usage-executing-prompts)
- [Store prompts and responses in SQLite](https://llm.datasette.io/en/stable/logging.html#logging)
- [Generate and store embeddings](https://llm.datasette.io/en/stable/embeddings/index.html#embeddings)
- [Extract structured content from text and images](https://llm.datasette.io/en/stable/schemas.html#schemas)
- [Grant models the ability to execute tools](https://llm.datasette.io/en/stable/tools.html#tools)
- … and much, much more

## Quick start

First, install LLM using `pip` or Homebrew or `pipx` or `uv`:

```bash
pip install llm
```

Or with Homebrew (see [warning note](https://llm.datasette.io/en/stable/setup.html#homebrew-warning)):

```bash
brew install llm
```

Or with [pipx](https://pipx.pypa.io/):

```bash
pipx install llm
```

Or with [uv](https://docs.astral.sh/uv/guides/tools/)

```bash
uv tool install llm
```

Use LLM to run prompts or start chats against an arbitrary OpenAI-compatible Chat Completions endpoint, such as [LM Studio](https://lmstudio.ai). With `uvx`, you can do this without installing LLM first:

```bash
uvx llm openai endpoint http://localhost:1234/v1 \
  -m google/gemma-4-12b \
  "What is the capital of France?"

uvx llm openai endpoint http://localhost:1234/v1 \
  -m google/gemma-4-12b \
  --chat
```

Add `--key your-api-key` if the endpoint requires authentication. See [Run against an endpoint without configuring it](https://llm.datasette.io/en/stable/other-models.html#openai-endpoint) for more options.

If you have an [OpenAI API key](https://platform.openai.com/api-keys) key you can run this:

```bash
# Paste your OpenAI API key into this
llm keys set openai

# Run a prompt (with the default gpt-6-luna model)
llm "Ten fun names for a pet pelican"

# Extract text from an image
llm "extract text" -a scanned-document.jpg

# Use a system prompt against a file
cat myfile.py | llm -s "Explain this code"
```

Run prompts against [Gemini](https://aistudio.google.com/apikey) or [Anthropic](https://console.anthropic.com/) with their respective plugins:

```bash
llm install llm-gemini
llm keys set gemini
# Paste Gemini API key here
llm -m gemini-3.5-flash 'Tell me fun facts about Mountain View'

llm install llm-anthropic
llm keys set anthropic
# Paste Anthropic API key here
llm -m claude-sonnet-5 'Impress me with wild facts about turnips'
```

You can also [install a plugin](https://llm.datasette.io/en/stable/plugins/installing-plugins.html#installing-plugins) to access models that can run on your local device. If you use [Ollama](https://ollama.com/):

```bash
# Install the plugin
llm install llm-ollama

# Download and run a prompt against the Orca Mini 7B model
ollama pull llama3.2:latest
llm -m llama3.2:latest 'What is the capital of France?'
```

To start [an interactive chat](https://llm.datasette.io/en/stable/usage.html#usage-chat) with a model, use `llm chat`:

```bash
llm chat -m gpt-4.1
```

```default
Chatting with gpt-4.1
Type 'exit' or 'quit' to exit
Type '!multi' to enter multiple lines, then '!end' to finish
Type '!edit' to open your default editor and modify the prompt.
Type '!fragment <my_fragment> [<another_fragment> ...]' to insert one or more fragments
> Tell me a joke about a pelican
Why don't pelicans like to tip waiters?

Because they always have a big bill!
```

## Project news

- 29th April 2026: [LLM 0.32a0 is a major backwards-compatible refactor](https://simonwillison.net/2026/Apr/29/llm/)
- 11th August 2025: [LLM 0.27, the annotated release notes: GPT-5 and improved tool calling](https://simonwillison.net/2025/Aug/11/llm-027/)
- 27th May 2025: [Large Language Models can run tools in your terminal with LLM 0.26](https://simonwillison.net/2025/May/27/llm-tools/)
- 5th May 2025: [Feed a video to a vision LLM as a sequence of JPEG frames on the CLI (also LLM 0.25)](https://simonwillison.net/2025/May/5/llm-video-frames/)
- 7th April 2025: [Long context support in LLM 0.24 using fragments and template plugins](https://simonwillison.net/2025/Apr/7/long-context-llm/)
- 28th February 2025: [Structured data extraction from unstructured content using LLM schemas](https://simonwillison.net/2025/Feb/28/llm-schemas/)
- 17th February 2025: [LLM 0.22, the annotated release notes](https://simonwillison.net/2025/Feb/17/llm/)
- 29th October 2024: [You can now run prompts against images, audio and video in your terminal using LLM](https://simonwillison.net/2024/Oct/29/llm-multi-modal/)
- 26th January 2024: [LLM 0.13: The annotated release notes](https://simonwillison.net/2024/Jan/26/llm/)
- 12th September 2023: [Build an image search engine with llm-clip, chat with models with llm chat](https://simonwillison.net/2023/Sep/12/llm-clip-and-chat/)
- 4th September 2023: [LLM now provides tools for working with embeddings](https://simonwillison.net/2023/Sep/4/llm-embeddings/)
- 12th July 2023: [The LLM CLI tool now supports self-hosted language models via plugins](https://simonwillison.net/2023/Jul/12/llm/)
- 18th May 2023: [llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/)
- 4th April 2023: [The original announcement of the llm CLI tool](https://simonwillison.net/2023/Apr/4/llm/)

For everything else, see [the llm tag](https://simonwillison.net/tags/llm/) on my blog.

## Contents

* [Setup](https://llm.datasette.io/en/stable/setup.html)
  * [Installation](https://llm.datasette.io/en/stable/setup.html#installation)
  * [Upgrading to the latest version](https://llm.datasette.io/en/stable/setup.html#upgrading-to-the-latest-version)
  * [Using uvx](https://llm.datasette.io/en/stable/setup.html#setup-uvx)
  * [A note about Homebrew and PyTorch](https://llm.datasette.io/en/stable/setup.html#homebrew-warning)
  * [Installing plugins](https://llm.datasette.io/en/stable/setup.html#installing-plugins)
  * [API key management](https://llm.datasette.io/en/stable/setup.html#api-keys)
    * [Saving and using stored keys](https://llm.datasette.io/en/stable/setup.html#saving-and-using-stored-keys)
    * [Passing keys using the –key option](https://llm.datasette.io/en/stable/setup.html#passing-keys-using-the-key-option)
    * [Keys in environment variables](https://llm.datasette.io/en/stable/setup.html#keys-in-environment-variables)
  * [Configuration](https://llm.datasette.io/en/stable/setup.html#configuration)
    * [Setting a custom default model](https://llm.datasette.io/en/stable/setup.html#setup-default-model)
    * [Setting a custom directory location](https://llm.datasette.io/en/stable/setup.html#setting-a-custom-directory-location)
    * [Turning SQLite logging on and off](https://llm.datasette.io/en/stable/setup.html#turning-sqlite-logging-on-and-off)
* [Usage](https://llm.datasette.io/en/stable/usage.html)
  * [Executing a prompt](https://llm.datasette.io/en/stable/usage.html#usage-executing-prompts)
    * [Model options](https://llm.datasette.io/en/stable/usage.html#usage-model-options)
    * [Attachments](https://llm.datasette.io/en/stable/usage.html#usage-attachments)
    * [System prompts](https://llm.datasette.io/en/stable/usage.html#usage-system-prompts)
    * [Tools](https://llm.datasette.io/en/stable/usage.html#usage-tools)
    * [Extracting fenced code blocks](https://llm.datasette.io/en/stable/usage.html#usage-extract-fenced-code)
    * [JSON output](https://llm.datasette.io/en/stable/usage.html#usage-json-output)
    * [Schemas](https://llm.datasette.io/en/stable/usage.html#usage-schemas)
    * [Fragments](https://llm.datasette.io/en/stable/usage.html#usage-fragments)
    * [Continuing a conversation](https://llm.datasette.io/en/stable/usage.html#usage-conversation)
    * [Tips for using LLM with Bash or Zsh](https://llm.datasette.io/en/stable/usage.html#tips-for-using-llm-with-bash-or-zsh)
    * [Completion prompts](https://llm.datasette.io/en/stable/usage.html#usage-completion-prompts)
  * [Starting an interactive chat](https://llm.datasette.io/en/stable/usage.html#usage-chat)
  * [Listing available models](https://llm.datasette.io/en/stable/usage.html#listing-available-models)
  * [Setting default options for models](https://llm.datasette.io/en/stable/usage.html#usage-executing-default-options)
* [OpenAI models](https://llm.datasette.io/en/stable/openai-models.html)
  * [Configuration](https://llm.datasette.io/en/stable/openai-models.html#openai-models-configuration)
  * [OpenAI language models](https://llm.datasette.io/en/stable/openai-models.html#openai-models-language)
  * [Model features](https://llm.datasette.io/en/stable/openai-models.html#model-features)
  * [Web Search](https://llm.datasette.io/en/stable/openai-models.html#openai-models-web-search)
  * [Code Interpreter](https://llm.datasette.io/en/stable/openai-models.html#openai-models-code-interpreter)
  * [Fast mode and service tiers](https://llm.datasette.io/en/stable/openai-models.html#openai-models-service-tier)
  * [OpenAI embedding models](https://llm.datasette.io/en/stable/openai-models.html#openai-models-embedding)
  * [OpenAI completion models](https://llm.datasette.io/en/stable/openai-models.html#openai-completion-models)
  * [Adding more OpenAI models](https://llm.datasette.io/en/stable/openai-models.html#openai-extra-models)
* [Other models](https://llm.datasette.io/en/stable/other-models.html)
  * [Installing and using a local model](https://llm.datasette.io/en/stable/other-models.html#installing-and-using-a-local-model)
  * [OpenAI-compatible models](https://llm.datasette.io/en/stable/other-models.html#openai-compatible-models)
    * [Run against an endpoint without configuring it](https://llm.datasette.io/en/stable/other-models.html#openai-endpoint)
    * [Configure an OpenAI-compatible model](https://llm.datasette.io/en/stable/other-models.html#openai-endpoint-add)
    * [Listing and removing configured models](https://llm.datasette.io/en/stable/other-models.html#listing-and-removing-configured-models)
    * [Extra HTTP headers](https://llm.datasette.io/en/stable/other-models.html#extra-http-headers)
* [Tools](https://llm.datasette.io/en/stable/tools.html)
  * [How tools work](https://llm.datasette.io/en/stable/tools.html#tools-how-they-work)
  * [Trying out tools](https://llm.datasette.io/en/stable/tools.html#tools-trying-out)
  * [LLM’s implementation of tools](https://llm.datasette.io/en/stable/tools.html#tools-implementation)
  * [Default tools](https://llm.datasette.io/en/stable/tools.html#tools-default)
  * [Tips for implementing tools](https://llm.datasette.io/en/stable/tools.html#tools-tips)
* [Schemas](https://llm.datasette.io/en/stable/schemas.html)
  * [Schemas tutorial](https://llm.datasette.io/en/stable/schemas.html#schemas-tutorial)
    * [Getting started with dogs](https://llm.datasette.io/en/stable/schemas.html#getting-started-with-dogs)
    * [Extracting people from a news articles](https://llm.datasette.io/en/stable/schemas.html#extracting-people-from-a-news-articles)
  * [Using JSON schemas](https://llm.datasette.io/en/stable/schemas.html#schemas-json-schemas)
  * [Ways to specify a schema](https://llm.datasette.io/en/stable/schemas.html#schemas-specify)
  * [Concise LLM schema syntax](https://llm.datasette.io/en/stable/schemas.html#schemas-dsl)
  * [Saving reusable schemas in templates](https://llm.datasette.io/en/stable/schemas.html#schemas-reusable)
  * [Browsing logged JSON objects created using schemas](https://llm.datasette.io/en/stable/schemas.html#schemas-logs)
* [Templates](https://llm.datasette.io/en/stable/templates.html)
  * [Getting started with <code>–save</code>](https://llm.datasette.io/en/stable/templates.html#prompt-templates-save)
  * [Using a template](https://llm.datasette.io/en/stable/templates.html#prompt-templates-using)
  * [Listing available templates](https://llm.datasette.io/en/stable/templates.html#prompt-templates-list)
  * [Templates as YAML files](https://llm.datasette.io/en/stable/templates.html#prompt-templates-yaml)
    * [System prompts](https://llm.datasette.io/en/stable/templates.html#prompt-templates-system)
    * [Fragments](https://llm.datasette.io/en/stable/templates.html#prompt-templates-fragments)
    * [Options](https://llm.datasette.io/en/stable/templates.html#prompt-templates-options)
    * [Tools](https://llm.datasette.io/en/stable/templates.html#prompt-templates-tools)
    * [Schemas](https://llm.datasette.io/en/stable/templates.html#prompt-templates-schemas)
    * [Additional template variables](https://llm.datasette.io/en/stable/templates.html#prompt-templates-variables)
    * [Specifying default parameters](https://llm.datasette.io/en/stable/templates.html#prompt-default-parameters)
    * [Configuring code extraction](https://llm.datasette.io/en/stable/templates.html#prompt-templates-extract)
    * [Setting a default model for a template](https://llm.datasette.io/en/stable/templates.html#prompt-templates-default-model)
  * [Template loaders from plugins](https://llm.datasette.io/en/stable/templates.html#prompt-templates-loaders)
* [Fragments](https://llm.datasette.io/en/stable/fragments.html)
  * [Using fragments in a prompt](https://llm.datasette.io/en/stable/fragments.html#fragments-usage)
  * [Using fragments in chat](https://llm.datasette.io/en/stable/fragments.html#using-fragments-in-chat)
  * [Browsing fragments](https://llm.datasette.io/en/stable/fragments.html#fragments-browsing)
  * [Setting aliases for fragments](https://llm.datasette.io/en/stable/fragments.html#fragments-aliases)
  * [Viewing fragments in your logs](https://llm.datasette.io/en/stable/fragments.html#fragments-logs)
  * [Using fragments from plugins](https://llm.datasette.io/en/stable/fragments.html#fragments-plugins)
  * [Listing available fragment prefixes](https://llm.datasette.io/en/stable/fragments.html#fragments-loaders)
* [Model aliases](https://llm.datasette.io/en/stable/aliases.html)
  * [Listing aliases](https://llm.datasette.io/en/stable/aliases.html#listing-aliases)
  * [Adding a new alias](https://llm.datasette.io/en/stable/aliases.html#adding-a-new-alias)
  * [Removing an alias](https://llm.datasette.io/en/stable/aliases.html#removing-an-alias)
  * [Viewing the aliases file](https://llm.datasette.io/en/stable/aliases.html#viewing-the-aliases-file)
* [Embeddings](https://llm.datasette.io/en/stable/embeddings/index.html)
  * [Embedding with the CLI](https://llm.datasette.io/en/stable/embeddings/cli.html)
    * [llm embed](https://llm.datasette.io/en/stable/embeddings/cli.html#embeddings-cli-embed)
    * [llm embed-multi](https://llm.datasette.io/en/stable/embeddings/cli.html#embeddings-cli-embed-multi)
    * [llm similar](https://llm.datasette.io/en/stable/embeddings/cli.html#embeddings-cli-similar)
    * [llm embed-models](https://llm.datasette.io/en/stable/embeddings/cli.html#embeddings-cli-embed-models)
    * [llm collections list](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-collections-list)
    * [llm collections delete](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-collections-delete)
  * [Using embeddings from Python](https://llm.datasette.io/en/stable/embeddings/python-api.html)
    * [Working with collections](https://llm.datasette.io/en/stable/embeddings/python-api.html#embeddings-python-collections)
    * [Retrieving similar items](https://llm.datasette.io/en/stable/embeddings/python-api.html#embeddings-python-similar)
    * [SQL schema](https://llm.datasette.io/en/stable/embeddings/python-api.html#embeddings-sql-schema)
  * [Writing plugins to add new embedding models](https://llm.datasette.io/en/stable/embeddings/writing-plugins.html)
    * [`EmbeddingModel`](https://llm.datasette.io/en/stable/embeddings/writing-plugins.html#llm.EmbeddingModel)
    * [Embedding binary content](https://llm.datasette.io/en/stable/embeddings/writing-plugins.html#embedding-binary-content)
    * [Embedding typed attachments](https://llm.datasette.io/en/stable/embeddings/writing-plugins.html#embedding-typed-attachments)
  * [Embedding storage format](https://llm.datasette.io/en/stable/embeddings/storage.html)
* [Plugins](https://llm.datasette.io/en/stable/plugins/index.html)
  * [Installing plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html)
    * [Listing installed plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html#listing-installed-plugins)
    * [Running with a subset of plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html#llm-load-plugins)
  * [Plugin directory](https://llm.datasette.io/en/stable/plugins/directory.html)
    * [Local models](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-local-models)
    * [Remote APIs](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-remote-apis)
    * [Tools](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-tools)
    * [Fragments and template loaders](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-loaders)
    * [Embedding models](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-embeddings)
    * [Extra commands](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-commands)
    * [Just for fun](https://llm.datasette.io/en/stable/plugins/directory.html#plugin-directory-fun)
  * [Plugin hooks](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html)
    * [register_commands(cli)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#plugin-hooks-register-commands)
    * [register_models(register, model_aliases)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#plugin-hooks-register-models)
    * [register_embedding_models(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#plugin-hooks-register-embedding-models)
    * [register_tools(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#plugin-hooks-register-tools)
    * [register_template_loaders(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#plugin-hooks-register-template-loaders)
    * [register_fragment_loaders(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#plugin-hooks-register-fragment-loaders)
  * [Developing a model plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html)
    * [The initial structure of the plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-initial)
    * [Installing your plugin to try it out](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-installing)
    * [Building the Markov chain](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-building)
    * [Executing the Markov chain](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-executing)
    * [Adding that to the plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-register)
    * [Understanding execute()](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-execute)
    * [Prompts and responses are logged to the database](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-logging)
    * [Adding options](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-options)
    * [Distributing your plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-distributing)
    * [GitHub repositories](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-github)
    * [Publishing plugins to PyPI](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-pypi)
    * [Adding metadata](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-metadata)
    * [What to do if it breaks](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#tutorial-model-plugin-breaks)
  * [Advanced model plugins](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html)
    * [Tip: lazily load expensive dependencies](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-lazy)
    * [Models that accept API keys](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-api-keys)
    * [Async models](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-async)
    * [Models that do not support conversations](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-conversations)
    * [Supporting schemas](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-schemas)
    * [Supporting tools](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-tools)
    * [Supporting server-side tools](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-server-side-tools)
    * [Attachments for multi-modal models](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-attachments)
    * [Structured messages and streaming events](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#structured-messages-streaming)
    * [Condensing logged payloads with json_replacements](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-json-replacements)
    * [Consuming prompt.messages in build_messages](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#consuming-prompt-messages-in-build-messages)
    * [Restoring opaque metadata on subsequent requests](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#restoring-opaque-metadata-on-subsequent-requests)
    * [Tracking token usage](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-usage)
    * [Tracking resolved model names](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#advanced-model-plugins-resolved-model)
    * [LLM_RAISE_ERRORS](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#tutorial-model-plugin-raise-errors)
  * [Utility functions for plugins](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html)
    * [llm.get_key()](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#plugin-utilities-get-key)
    * [llm.user_dir()](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#plugin-utilities-user-dir)
    * [llm.ModelError](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#plugin-utilities-modelerror)
    * [Response.fake()](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#plugin-utilities-response-fake)
* [Python API](https://llm.datasette.io/en/stable/python-api.html)
  * [Basic prompt execution](https://llm.datasette.io/en/stable/python-api.html#basic-prompt-execution)
    * [System prompts](https://llm.datasette.io/en/stable/python-api.html#python-api-system-prompts)
    * [Attachments](https://llm.datasette.io/en/stable/python-api.html#python-api-attachments)
    * [Tools](https://llm.datasette.io/en/stable/python-api.html#python-api-tools)
    * [Schemas](https://llm.datasette.io/en/stable/python-api.html#python-api-schemas)
    * [Fragments](https://llm.datasette.io/en/stable/python-api.html#python-api-fragments)
    * [Model options](https://llm.datasette.io/en/stable/python-api.html#python-api-model-options)
    * [Passing an API key](https://llm.datasette.io/en/stable/python-api.html#python-api-models-api-keys)
    * [Models from plugins](https://llm.datasette.io/en/stable/python-api.html#python-api-models-from-plugins)
    * [Accessing the underlying JSON](https://llm.datasette.io/en/stable/python-api.html#python-api-underlying-json)
    * [Token usage](https://llm.datasette.io/en/stable/python-api.html#python-api-token-usage)
    * [Streaming responses](https://llm.datasette.io/en/stable/python-api.html#python-api-streaming-responses)
    * [Structured messages and streaming events](https://llm.datasette.io/en/stable/python-api.html#python-api-messages)
  * [Async models](https://llm.datasette.io/en/stable/python-api.html#python-api-async)
    * [`AsyncResponse`](https://llm.datasette.io/en/stable/python-api.html#llm.AsyncResponse)
    * [Tool functions can be sync or async](https://llm.datasette.io/en/stable/python-api.html#python-api-async-tools)
    * [Tool use for async models](https://llm.datasette.io/en/stable/python-api.html#tool-use-for-async-models)
  * [Conversations](https://llm.datasette.io/en/stable/python-api.html#python-api-conversations)
    * [Conversations using tools](https://llm.datasette.io/en/stable/python-api.html#conversations-using-tools)
  * [Listing models](https://llm.datasette.io/en/stable/python-api.html#python-api-listing-models)
  * [Running code when a response has completed](https://llm.datasette.io/en/stable/python-api.html#python-api-response-on-done)
  * [Other functions](https://llm.datasette.io/en/stable/python-api.html#other-functions)
    * [set_alias(alias, model_id)](https://llm.datasette.io/en/stable/python-api.html#set-alias-alias-model-id)
    * [remove_alias(alias)](https://llm.datasette.io/en/stable/python-api.html#remove-alias-alias)
    * [set_default_model(alias)](https://llm.datasette.io/en/stable/python-api.html#set-default-model-alias)
    * [get_default_model()](https://llm.datasette.io/en/stable/python-api.html#get-default-model)
    * [set_default_embedding_model(alias) and get_default_embedding_model()](https://llm.datasette.io/en/stable/python-api.html#set-default-embedding-model-alias-and-get-default-embedding-model)
* [Logging to SQLite](https://llm.datasette.io/en/stable/logging.html)
  * [Viewing the logs](https://llm.datasette.io/en/stable/logging.html#logging-view)
    * [-s/–short mode](https://llm.datasette.io/en/stable/logging.html#logging-short)
    * [Logs for a conversation](https://llm.datasette.io/en/stable/logging.html#logging-conversation)
    * [Searching the logs](https://llm.datasette.io/en/stable/logging.html#logging-search)
    * [Filtering past a specific ID](https://llm.datasette.io/en/stable/logging.html#logging-filter-id)
    * [Filtering by model](https://llm.datasette.io/en/stable/logging.html#logging-filter-model)
    * [Filtering by prompts that used specific fragments](https://llm.datasette.io/en/stable/logging.html#logging-filter-fragments)
    * [Filtering by prompts that used specific tools](https://llm.datasette.io/en/stable/logging.html#logging-filter-tools)
    * [Browsing data collected using schemas](https://llm.datasette.io/en/stable/logging.html#logging-filter-schemas)
  * [Browsing logs using Datasette](https://llm.datasette.io/en/stable/logging.html#logging-datasette)
  * [Backing up your database](https://llm.datasette.io/en/stable/logging.html#logging-backup)
  * [The message store](https://llm.datasette.io/en/stable/logging.html#logging-message-store)
    * [Threads, turns, messages and parts](https://llm.datasette.io/en/stable/logging.html#logging-message-store-vocabulary)
    * [A worked example](https://llm.datasette.io/en/stable/logging.html#logging-message-store-example)
    * [Content addressing as a contract](https://llm.datasette.io/en/stable/logging.html#logging-message-store-hashes)
    * [Forking and shared history](https://llm.datasette.io/en/stable/logging.html#logging-message-store-forking)
    * [Storage by reference](https://llm.datasette.io/en/stable/logging.html#logging-message-store-references)
    * [The raw provider payload](https://llm.datasette.io/en/stable/logging.html#logging-message-store-response-json)
    * [Table by table](https://llm.datasette.io/en/stable/logging.html#logging-message-store-tables)
    * [Querying the message store](https://llm.datasette.io/en/stable/logging.html#logging-message-store-queries)
    * [Logging from Python](https://llm.datasette.io/en/stable/logging.html#logging-message-store-python)
  * [SQL schema](https://llm.datasette.io/en/stable/logging.html#logging-sql-schema)
* [Related tools](https://llm.datasette.io/en/stable/related-tools.html)
  * [strip-tags](https://llm.datasette.io/en/stable/related-tools.html#related-tools-strip-tags)
  * [ttok](https://llm.datasette.io/en/stable/related-tools.html#related-tools-ttok)
  * [Symbex](https://llm.datasette.io/en/stable/related-tools.html#related-tools-symbex)
* [CLI reference](https://llm.datasette.io/en/stable/help.html)
  * [llm  –help](https://llm.datasette.io/en/stable/help.html#help)
    * [llm prompt –help](https://llm.datasette.io/en/stable/help.html#help-prompt)
    * [llm chat –help](https://llm.datasette.io/en/stable/help.html#help-chat)
    * [llm keys –help](https://llm.datasette.io/en/stable/help.html#help-keys)
    * [llm logs –help](https://llm.datasette.io/en/stable/help.html#help-logs)
    * [llm models –help](https://llm.datasette.io/en/stable/help.html#help-models)
    * [llm templates –help](https://llm.datasette.io/en/stable/help.html#help-templates)
    * [llm schemas –help](https://llm.datasette.io/en/stable/help.html#help-schemas)
    * [llm tools –help](https://llm.datasette.io/en/stable/help.html#help-tools)
    * [llm aliases –help](https://llm.datasette.io/en/stable/help.html#help-aliases)
    * [llm fragments –help](https://llm.datasette.io/en/stable/help.html#help-fragments)
    * [llm plugins –help](https://llm.datasette.io/en/stable/help.html#help-plugins)
    * [llm install –help](https://llm.datasette.io/en/stable/help.html#help-install)
    * [llm uninstall –help](https://llm.datasette.io/en/stable/help.html#help-uninstall)
    * [llm embed –help](https://llm.datasette.io/en/stable/help.html#help-embed)
    * [llm embed-multi –help](https://llm.datasette.io/en/stable/help.html#help-embed-multi)
    * [llm similar –help](https://llm.datasette.io/en/stable/help.html#help-similar)
    * [llm embed-models –help](https://llm.datasette.io/en/stable/help.html#help-embed-models)
    * [llm collections –help](https://llm.datasette.io/en/stable/help.html#help-collections)
    * [llm openai –help](https://llm.datasette.io/en/stable/help.html#help-openai)
* [Contributing](https://llm.datasette.io/en/stable/contributing.html)
  * [Updating recorded HTTP API interactions and associated snapshots](https://llm.datasette.io/en/stable/contributing.html#updating-recorded-http-api-interactions-and-associated-snapshots)
  * [Debugging tricks](https://llm.datasette.io/en/stable/contributing.html#debugging-tricks)
  * [Documentation](https://llm.datasette.io/en/stable/contributing.html#documentation)
  * [Release process](https://llm.datasette.io/en/stable/contributing.html#release-process)

* [Changelog](https://llm.datasette.io/en/stable/changelog.html)
<!-- [[[end]]] -->
