# LLM

[![GitHub repo](https://img.shields.io/badge/github-repo-green)](https://github.com/simonw/llm)
[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/823971286308356157?label=discord)](https://datasette.io/discord-llm)
[![Homebrew](https://img.shields.io/homebrew/installs/dy/llm?color=yellow&label=homebrew&logo=homebrew)](https://formulae.brew.sh/formula/llm)

A CLI tool and Python library for interacting with **OpenAI**, **Anthropic's Claude**, **Google's Gemini**, **Meta's Llama** and dozens of other Large Language Models, both via remote APIs and with models that can be installed and run on your own machine.

Watch **[Language models on the command-line](https://www.youtube.com/watch?v=QUXQNi6jQ30)** on YouTube for a demo or [read the accompanying detailed notes](https://simonwillison.net/2024/Jun/17/cli-language-models/).

With LLM you can:
- {ref}`Run prompts from the command-line <usage-executing-prompts>`
- {ref}`Store prompts and responses in SQLite <logging>`
- {ref}`Generate and store embeddings <embeddings>`
- {ref}`Extract structured content from text and images <schemas>`
- {ref}`Grant models the ability to execute tools <tools>`
- ... and much, much more

## Quick start

First, install LLM using `pip` or Homebrew or `pipx` or `uv`:

```bash
pip install llm
```
Or with Homebrew (see {ref}`warning note <homebrew-warning>`):
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
You can also {ref}`install a plugin <installing-plugins>` to access models that can run on your local device. If you use [Ollama](https://ollama.com/):
```bash
# Install the plugin
llm install llm-ollama

# Download and run a prompt against the Orca Mini 7B model
ollama pull llama3.2:latest
llm -m llama3.2:latest 'What is the capital of France?'
```
To start {ref}`an interactive chat <usage-chat>` with a model, use `llm chat`:
```bash
llm chat -m gpt-4.1
```
```
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

```{toctree}
---
maxdepth: 3
---
setup
usage
openai-models
other-models
tools
schemas
templates
fragments
aliases
embeddings/index
plugins/index
python-api
logging
related-tools
help
contributing
```
```{toctree}
---
maxdepth: 1
---
changelog
```
