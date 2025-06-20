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

A CLI tool and Python library for interacting with **OpenAI**, **Anthropic’s Claude**, **Google’s Gemini**, **Meta’s Llama** and dozens of other Large Language Models, both via remote APIs and with models that can be installed and run on your own machine.

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

Or with [pipx](https://pypa.github.io/pipx/):

```bash
pipx install llm
```

Or with [uv](https://docs.astral.sh/uv/guides/tools/)

```bash
uv tool install llm
```

If you have an [OpenAI API key](https://platform.openai.com/api-keys) key you can run this:

```bash
# Paste your OpenAI API key into this
llm keys set openai

# Run a prompt (with the default gpt-4o-mini model)
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
llm -m gemini-2.0-flash 'Tell me fun facts about Mountain View'

llm install llm-anthropic
llm keys set anthropic
# Paste Anthropic API key here
llm -m claude-4-opus 'Impress me with wild facts about turnips'
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

More background on this project:

- [llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/)
- [The LLM CLI tool now supports self-hosted language models via plugins](https://simonwillison.net/2023/Jul/12/llm/)
- [LLM now provides tools for working with embeddings](https://simonwillison.net/2023/Sep/4/llm-embeddings/)
- [Build an image search engine with llm-clip, chat with models with llm chat](https://simonwillison.net/2023/Sep/12/llm-clip-and-chat/)
- [You can now run prompts against images, audio and video in your terminal using LLM](https://simonwillison.net/2024/Oct/29/llm-multi-modal/)
- [Structured data extraction from unstructured content using LLM schemas](https://simonwillison.net/2025/Feb/28/llm-schemas/)
- [Long context support in LLM 0.24 using fragments and template plugins](https://simonwillison.net/2025/Apr/7/long-context-llm/)

See also [the llm tag](https://simonwillison.net/tags/llm/) on my blog.

## Contents

* [Setup](https://llm.datasette.io/en/stable/setup.html)
  * [Installation](https://llm.datasette.io/en/stable/setup.html#installation)
  * [Upgrading to the latest version](https://llm.datasette.io/en/stable/setup.html#upgrading-to-the-latest-version)
  * [Using uvx](https://llm.datasette.io/en/stable/setup.html#using-uvx)
  * [A note about Homebrew and PyTorch](https://llm.datasette.io/en/stable/setup.html#a-note-about-homebrew-and-pytorch)
  * [Installing plugins](https://llm.datasette.io/en/stable/setup.html#installing-plugins)
  * [API key management](https://llm.datasette.io/en/stable/setup.html#api-key-management)
    * [Saving and using stored keys](https://llm.datasette.io/en/stable/setup.html#saving-and-using-stored-keys)
    * [Passing keys using the –key option](https://llm.datasette.io/en/stable/setup.html#passing-keys-using-the-key-option)
    * [Keys in environment variables](https://llm.datasette.io/en/stable/setup.html#keys-in-environment-variables)
  * [Configuration](https://llm.datasette.io/en/stable/setup.html#configuration)
    * [Setting a custom default model](https://llm.datasette.io/en/stable/setup.html#setting-a-custom-default-model)
    * [Setting a custom directory location](https://llm.datasette.io/en/stable/setup.html#setting-a-custom-directory-location)
    * [Turning SQLite logging on and off](https://llm.datasette.io/en/stable/setup.html#turning-sqlite-logging-on-and-off)
* [Usage](https://llm.datasette.io/en/stable/usage.html)
  * [Executing a prompt](https://llm.datasette.io/en/stable/usage.html#executing-a-prompt)
    * [Model options](https://llm.datasette.io/en/stable/usage.html#model-options)
    * [Attachments](https://llm.datasette.io/en/stable/usage.html#attachments)
    * [System prompts](https://llm.datasette.io/en/stable/usage.html#system-prompts)
    * [Tools](https://llm.datasette.io/en/stable/usage.html#tools)
    * [Extracting fenced code blocks](https://llm.datasette.io/en/stable/usage.html#extracting-fenced-code-blocks)
    * [Schemas](https://llm.datasette.io/en/stable/usage.html#schemas)
    * [Fragments](https://llm.datasette.io/en/stable/usage.html#fragments)
    * [Continuing a conversation](https://llm.datasette.io/en/stable/usage.html#continuing-a-conversation)
    * [Tips for using LLM with Bash or Zsh](https://llm.datasette.io/en/stable/usage.html#tips-for-using-llm-with-bash-or-zsh)
    * [Completion prompts](https://llm.datasette.io/en/stable/usage.html#completion-prompts)
  * [Starting an interactive chat](https://llm.datasette.io/en/stable/usage.html#starting-an-interactive-chat)
  * [Listing available models](https://llm.datasette.io/en/stable/usage.html#listing-available-models)
  * [Setting default options for models](https://llm.datasette.io/en/stable/usage.html#setting-default-options-for-models)
* [OpenAI models](https://llm.datasette.io/en/stable/openai-models.html)
  * [Configuration](https://llm.datasette.io/en/stable/openai-models.html#configuration)
  * [OpenAI language models](https://llm.datasette.io/en/stable/openai-models.html#openai-language-models)
  * [Model features](https://llm.datasette.io/en/stable/openai-models.html#model-features)
  * [OpenAI embedding models](https://llm.datasette.io/en/stable/openai-models.html#openai-embedding-models)
  * [OpenAI completion models](https://llm.datasette.io/en/stable/openai-models.html#openai-completion-models)
  * [Adding more OpenAI models](https://llm.datasette.io/en/stable/openai-models.html#adding-more-openai-models)
* [Other models](https://llm.datasette.io/en/stable/other-models.html)
  * [Installing and using a local model](https://llm.datasette.io/en/stable/other-models.html#installing-and-using-a-local-model)
  * [OpenAI-compatible models](https://llm.datasette.io/en/stable/other-models.html#openai-compatible-models)
    * [Extra HTTP headers](https://llm.datasette.io/en/stable/other-models.html#extra-http-headers)
* [Tools](https://llm.datasette.io/en/stable/tools.html)
  * [How tools work](https://llm.datasette.io/en/stable/tools.html#how-tools-work)
  * [Trying out tools](https://llm.datasette.io/en/stable/tools.html#trying-out-tools)
  * [LLM’s implementation of tools](https://llm.datasette.io/en/stable/tools.html#llm-s-implementation-of-tools)
  * [Default tools](https://llm.datasette.io/en/stable/tools.html#default-tools)
  * [Tips for implementing tools](https://llm.datasette.io/en/stable/tools.html#tips-for-implementing-tools)
* [Schemas](https://llm.datasette.io/en/stable/schemas.html)
  * [Schemas tutorial](https://llm.datasette.io/en/stable/schemas.html#schemas-tutorial)
    * [Getting started with dogs](https://llm.datasette.io/en/stable/schemas.html#getting-started-with-dogs)
    * [Extracting people from a news articles](https://llm.datasette.io/en/stable/schemas.html#extracting-people-from-a-news-articles)
  * [Using JSON schemas](https://llm.datasette.io/en/stable/schemas.html#using-json-schemas)
  * [Ways to specify a schema](https://llm.datasette.io/en/stable/schemas.html#ways-to-specify-a-schema)
  * [Concise LLM schema syntax](https://llm.datasette.io/en/stable/schemas.html#concise-llm-schema-syntax)
  * [Saving reusable schemas in templates](https://llm.datasette.io/en/stable/schemas.html#saving-reusable-schemas-in-templates)
  * [Browsing logged JSON objects created using schemas](https://llm.datasette.io/en/stable/schemas.html#browsing-logged-json-objects-created-using-schemas)
* [Templates](https://llm.datasette.io/en/stable/templates.html)
  * [Getting started with <code>–save</code>](https://llm.datasette.io/en/stable/templates.html#getting-started-with-save)
  * [Using a template](https://llm.datasette.io/en/stable/templates.html#using-a-template)
  * [Listing available templates](https://llm.datasette.io/en/stable/templates.html#listing-available-templates)
  * [Templates as YAML files](https://llm.datasette.io/en/stable/templates.html#templates-as-yaml-files)
    * [System prompts](https://llm.datasette.io/en/stable/templates.html#system-prompts)
    * [Fragments](https://llm.datasette.io/en/stable/templates.html#fragments)
    * [Options](https://llm.datasette.io/en/stable/templates.html#options)
    * [Tools](https://llm.datasette.io/en/stable/templates.html#tools)
    * [Schemas](https://llm.datasette.io/en/stable/templates.html#schemas)
    * [Additional template variables](https://llm.datasette.io/en/stable/templates.html#additional-template-variables)
    * [Specifying default parameters](https://llm.datasette.io/en/stable/templates.html#specifying-default-parameters)
    * [Configuring code extraction](https://llm.datasette.io/en/stable/templates.html#configuring-code-extraction)
    * [Setting a default model for a template](https://llm.datasette.io/en/stable/templates.html#setting-a-default-model-for-a-template)
  * [Template loaders from plugins](https://llm.datasette.io/en/stable/templates.html#template-loaders-from-plugins)
* [Fragments](https://llm.datasette.io/en/stable/fragments.html)
  * [Using fragments in a prompt](https://llm.datasette.io/en/stable/fragments.html#using-fragments-in-a-prompt)
  * [Using fragments in chat](https://llm.datasette.io/en/stable/fragments.html#using-fragments-in-chat)
  * [Browsing fragments](https://llm.datasette.io/en/stable/fragments.html#browsing-fragments)
  * [Setting aliases for fragments](https://llm.datasette.io/en/stable/fragments.html#setting-aliases-for-fragments)
  * [Viewing fragments in your logs](https://llm.datasette.io/en/stable/fragments.html#viewing-fragments-in-your-logs)
  * [Using fragments from plugins](https://llm.datasette.io/en/stable/fragments.html#using-fragments-from-plugins)
  * [Listing available fragment prefixes](https://llm.datasette.io/en/stable/fragments.html#listing-available-fragment-prefixes)
* [Model aliases](https://llm.datasette.io/en/stable/aliases.html)
  * [Listing aliases](https://llm.datasette.io/en/stable/aliases.html#listing-aliases)
  * [Adding a new alias](https://llm.datasette.io/en/stable/aliases.html#adding-a-new-alias)
  * [Removing an alias](https://llm.datasette.io/en/stable/aliases.html#removing-an-alias)
  * [Viewing the aliases file](https://llm.datasette.io/en/stable/aliases.html#viewing-the-aliases-file)
* [Embeddings](https://llm.datasette.io/en/stable/embeddings/index.html)
  * [Embedding with the CLI](https://llm.datasette.io/en/stable/embeddings/cli.html)
    * [llm embed](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-embed)
    * [llm embed-multi](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-embed-multi)
    * [llm similar](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-similar)
    * [llm embed-models](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-embed-models)
    * [llm collections list](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-collections-list)
    * [llm collections delete](https://llm.datasette.io/en/stable/embeddings/cli.html#llm-collections-delete)
  * [Using embeddings from Python](https://llm.datasette.io/en/stable/embeddings/python-api.html)
    * [Working with collections](https://llm.datasette.io/en/stable/embeddings/python-api.html#working-with-collections)
    * [Retrieving similar items](https://llm.datasette.io/en/stable/embeddings/python-api.html#retrieving-similar-items)
    * [SQL schema](https://llm.datasette.io/en/stable/embeddings/python-api.html#sql-schema)
  * [Writing plugins to add new embedding models](https://llm.datasette.io/en/stable/embeddings/writing-plugins.html)
    * [Embedding binary content](https://llm.datasette.io/en/stable/embeddings/writing-plugins.html#embedding-binary-content)
  * [Embedding storage format](https://llm.datasette.io/en/stable/embeddings/storage.html)
* [Plugins](https://llm.datasette.io/en/stable/plugins/index.html)
  * [Installing plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html)
    * [Listing installed plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html#listing-installed-plugins)
    * [Running with a subset of plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html#running-with-a-subset-of-plugins)
  * [Plugin directory](https://llm.datasette.io/en/stable/plugins/directory.html)
    * [Local models](https://llm.datasette.io/en/stable/plugins/directory.html#local-models)
    * [Remote APIs](https://llm.datasette.io/en/stable/plugins/directory.html#remote-apis)
    * [Tools](https://llm.datasette.io/en/stable/plugins/directory.html#tools)
    * [Fragments and template loaders](https://llm.datasette.io/en/stable/plugins/directory.html#fragments-and-template-loaders)
    * [Embedding models](https://llm.datasette.io/en/stable/plugins/directory.html#embedding-models)
    * [Extra commands](https://llm.datasette.io/en/stable/plugins/directory.html#extra-commands)
    * [Just for fun](https://llm.datasette.io/en/stable/plugins/directory.html#just-for-fun)
  * [Plugin hooks](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html)
    * [register_commands(cli)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#register-commands-cli)
    * [register_models(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#register-models-register)
    * [register_embedding_models(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#register-embedding-models-register)
    * [register_tools(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#register-tools-register)
    * [register_template_loaders(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#register-template-loaders-register)
    * [register_fragment_loaders(register)](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html#register-fragment-loaders-register)
  * [Developing a model plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html)
    * [The initial structure of the plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#the-initial-structure-of-the-plugin)
    * [Installing your plugin to try it out](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#installing-your-plugin-to-try-it-out)
    * [Building the Markov chain](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#building-the-markov-chain)
    * [Executing the Markov chain](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#executing-the-markov-chain)
    * [Adding that to the plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#adding-that-to-the-plugin)
    * [Understanding execute()](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#understanding-execute)
    * [Prompts and responses are logged to the database](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#prompts-and-responses-are-logged-to-the-database)
    * [Adding options](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#adding-options)
    * [Distributing your plugin](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#distributing-your-plugin)
    * [GitHub repositories](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#github-repositories)
    * [Publishing plugins to PyPI](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#publishing-plugins-to-pypi)
    * [Adding metadata](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#adding-metadata)
    * [What to do if it breaks](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html#what-to-do-if-it-breaks)
  * [Advanced model plugins](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html)
    * [Tip: lazily load expensive dependencies](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#tip-lazily-load-expensive-dependencies)
    * [Models that accept API keys](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#models-that-accept-api-keys)
    * [Async models](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#async-models)
    * [Supporting schemas](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#supporting-schemas)
    * [Supporting tools](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#supporting-tools)
    * [Attachments for multi-modal models](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#attachments-for-multi-modal-models)
    * [Tracking token usage](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#tracking-token-usage)
    * [Tracking resolved model names](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#tracking-resolved-model-names)
    * [LLM_RAISE_ERRORS](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#llm-raise-errors)
  * [Utility functions for plugins](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html)
    * [llm.get_key()](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#llm-get-key)
    * [llm.user_dir()](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#llm-user-dir)
    * [llm.ModelError](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#llm-modelerror)
    * [Response.fake()](https://llm.datasette.io/en/stable/plugins/plugin-utilities.html#response-fake)
* [Python API](https://llm.datasette.io/en/stable/python-api.html)
  * [Basic prompt execution](https://llm.datasette.io/en/stable/python-api.html#basic-prompt-execution)
    * [System prompts](https://llm.datasette.io/en/stable/python-api.html#system-prompts)
    * [Attachments](https://llm.datasette.io/en/stable/python-api.html#attachments)
    * [Tools](https://llm.datasette.io/en/stable/python-api.html#tools)
    * [Schemas](https://llm.datasette.io/en/stable/python-api.html#schemas)
    * [Fragments](https://llm.datasette.io/en/stable/python-api.html#fragments)
    * [Model options](https://llm.datasette.io/en/stable/python-api.html#model-options)
    * [Passing an API key](https://llm.datasette.io/en/stable/python-api.html#passing-an-api-key)
    * [Models from plugins](https://llm.datasette.io/en/stable/python-api.html#models-from-plugins)
    * [Accessing the underlying JSON](https://llm.datasette.io/en/stable/python-api.html#accessing-the-underlying-json)
    * [Token usage](https://llm.datasette.io/en/stable/python-api.html#token-usage)
    * [Streaming responses](https://llm.datasette.io/en/stable/python-api.html#streaming-responses)
  * [Async models](https://llm.datasette.io/en/stable/python-api.html#async-models)
    * [Tool functions can be sync or async](https://llm.datasette.io/en/stable/python-api.html#tool-functions-can-be-sync-or-async)
    * [Tool use for async models](https://llm.datasette.io/en/stable/python-api.html#tool-use-for-async-models)
  * [Conversations](https://llm.datasette.io/en/stable/python-api.html#conversations)
    * [Conversations using tools](https://llm.datasette.io/en/stable/python-api.html#conversations-using-tools)
  * [Listing models](https://llm.datasette.io/en/stable/python-api.html#listing-models)
  * [Running code when a response has completed](https://llm.datasette.io/en/stable/python-api.html#running-code-when-a-response-has-completed)
  * [Other functions](https://llm.datasette.io/en/stable/python-api.html#other-functions)
    * [set_alias(alias, model_id)](https://llm.datasette.io/en/stable/python-api.html#set-alias-alias-model-id)
    * [remove_alias(alias)](https://llm.datasette.io/en/stable/python-api.html#remove-alias-alias)
    * [set_default_model(alias)](https://llm.datasette.io/en/stable/python-api.html#set-default-model-alias)
    * [get_default_model()](https://llm.datasette.io/en/stable/python-api.html#get-default-model)
    * [set_default_embedding_model(alias) and get_default_embedding_model()](https://llm.datasette.io/en/stable/python-api.html#set-default-embedding-model-alias-and-get-default-embedding-model)
* [Logging to SQLite](https://llm.datasette.io/en/stable/logging.html)
  * [Viewing the logs](https://llm.datasette.io/en/stable/logging.html#viewing-the-logs)
    * [-s/–short mode](https://llm.datasette.io/en/stable/logging.html#s-short-mode)
    * [Logs for a conversation](https://llm.datasette.io/en/stable/logging.html#logs-for-a-conversation)
    * [Searching the logs](https://llm.datasette.io/en/stable/logging.html#searching-the-logs)
    * [Filtering past a specific ID](https://llm.datasette.io/en/stable/logging.html#filtering-past-a-specific-id)
    * [Filtering by model](https://llm.datasette.io/en/stable/logging.html#filtering-by-model)
    * [Filtering by prompts that used specific fragments](https://llm.datasette.io/en/stable/logging.html#filtering-by-prompts-that-used-specific-fragments)
    * [Filtering by prompts that used specific tools](https://llm.datasette.io/en/stable/logging.html#filtering-by-prompts-that-used-specific-tools)
    * [Browsing data collected using schemas](https://llm.datasette.io/en/stable/logging.html#browsing-data-collected-using-schemas)
  * [Browsing logs using Datasette](https://llm.datasette.io/en/stable/logging.html#browsing-logs-using-datasette)
  * [Backing up your database](https://llm.datasette.io/en/stable/logging.html#backing-up-your-database)
  * [SQL schema](https://llm.datasette.io/en/stable/logging.html#sql-schema)
* [Related tools](https://llm.datasette.io/en/stable/related-tools.html)
  * [strip-tags](https://llm.datasette.io/en/stable/related-tools.html#strip-tags)
  * [ttok](https://llm.datasette.io/en/stable/related-tools.html#ttok)
  * [Symbex](https://llm.datasette.io/en/stable/related-tools.html#symbex)
* [CLI reference](https://llm.datasette.io/en/stable/help.html)
  * [llm  –help](https://llm.datasette.io/en/stable/help.html#llm-help)
    * [llm prompt –help](https://llm.datasette.io/en/stable/help.html#llm-prompt-help)
    * [llm chat –help](https://llm.datasette.io/en/stable/help.html#llm-chat-help)
    * [llm keys –help](https://llm.datasette.io/en/stable/help.html#llm-keys-help)
    * [llm logs –help](https://llm.datasette.io/en/stable/help.html#llm-logs-help)
    * [llm models –help](https://llm.datasette.io/en/stable/help.html#llm-models-help)
    * [llm templates –help](https://llm.datasette.io/en/stable/help.html#llm-templates-help)
    * [llm schemas –help](https://llm.datasette.io/en/stable/help.html#llm-schemas-help)
    * [llm tools –help](https://llm.datasette.io/en/stable/help.html#llm-tools-help)
    * [llm aliases –help](https://llm.datasette.io/en/stable/help.html#llm-aliases-help)
    * [llm fragments –help](https://llm.datasette.io/en/stable/help.html#llm-fragments-help)
    * [llm plugins –help](https://llm.datasette.io/en/stable/help.html#llm-plugins-help)
    * [llm install –help](https://llm.datasette.io/en/stable/help.html#llm-install-help)
    * [llm uninstall –help](https://llm.datasette.io/en/stable/help.html#llm-uninstall-help)
    * [llm embed –help](https://llm.datasette.io/en/stable/help.html#llm-embed-help)
    * [llm embed-multi –help](https://llm.datasette.io/en/stable/help.html#llm-embed-multi-help)
    * [llm similar –help](https://llm.datasette.io/en/stable/help.html#llm-similar-help)
    * [llm embed-models –help](https://llm.datasette.io/en/stable/help.html#llm-embed-models-help)
    * [llm collections –help](https://llm.datasette.io/en/stable/help.html#llm-collections-help)
    * [llm openai –help](https://llm.datasette.io/en/stable/help.html#llm-openai-help)
* [Contributing](https://llm.datasette.io/en/stable/contributing.html)
  * [Updating recorded HTTP API interactions and associated snapshots](https://llm.datasette.io/en/stable/contributing.html#updating-recorded-http-api-interactions-and-associated-snapshots)
  * [Debugging tricks](https://llm.datasette.io/en/stable/contributing.html#debugging-tricks)
  * [Documentation](https://llm.datasette.io/en/stable/contributing.html#documentation)
  * [Release process](https://llm.datasette.io/en/stable/contributing.html#release-process)

* [Changelog](https://llm.datasette.io/en/stable/changelog.html)
<!-- [[[end]]] -->
