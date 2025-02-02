# LLM

[![GitHub repo](https://img.shields.io/badge/github-repo-green)](https://github.com/simonw/llm)
[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/823971286308356157?label=discord)](https://datasette.io/discord-llm)
[![Homebrew](https://img.shields.io/homebrew/installs/dy/llm?color=yellow&label=homebrew&logo=homebrew)](https://formulae.brew.sh/formula/llm)

A CLI utility and Python library for interacting with Large Language Models, both via remote APIs and models that can be installed and run on your own machine.

{ref}`Run prompts from the command-line <usage-executing-prompts>`, {ref}`store the results in SQLite <logging>`, {ref}`generate embeddings <embeddings>` and more.

Here's a [YouTube video demo](https://www.youtube.com/watch?v=QUXQNi6jQ30) and [accompanying detailed notes](https://simonwillison.net/2024/Jun/17/cli-language-models/).

Background on this project:
- [llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/)
- [The LLM CLI tool now supports self-hosted language models via plugins](https://simonwillison.net/2023/Jul/12/llm/)
- [Accessing Llama 2 from the command-line with the llm-replicate plugin](https://simonwillison.net/2023/Jul/18/accessing-llama-2/)
- [Run Llama 2 on your own Mac using LLM and Homebrew](https://simonwillison.net/2023/Aug/1/llama-2-mac/)
- [Catching up on the weird world of LLMs](https://simonwillison.net/2023/Aug/3/weird-world-of-llms/)
- [LLM now provides tools for working with embeddings](https://simonwillison.net/2023/Sep/4/llm-embeddings/)
- [Build an image search engine with llm-clip, chat with models with llm chat](https://simonwillison.net/2023/Sep/12/llm-clip-and-chat/)
- [Many options for running Mistral models in your terminal using LLM](https://simonwillison.net/2023/Dec/18/mistral/)

For more check out [the llm tag](https://simonwillison.net/tags/llm/) on my blog.

## Quick start

First, install LLM using `pip` or Homebrew or `pipx`:

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
Or you can {ref}`install a plugin <installing-plugins>` and use models that can run on your local device:
```bash
# Install the plugin
llm install llm-gpt4all

# Download and run a prompt against the Orca Mini 7B model
llm -m orca-mini-3b-gguf2-q4_0 'What is the capital of France?'
```
To start {ref}`an interactive chat <usage-chat>` with a model, use `llm chat`:
```bash
llm chat -m gpt-4o
```
```
Chatting with gpt-4o
Type 'exit' or 'quit' to exit
Type '!multi' to enter multiple lines, then '!end' to finish
Type '!attach file' to attach a file to this chat
> Tell me a joke about a pelican
Why don't pelicans like to tip waiters?

Because they always have a big bill!
>
```

## Contents

```{toctree}
---
maxdepth: 3
---
setup
usage
openai-models
other-models
embeddings/index
plugins/index
aliases
python-api
templates
logging
related-tools
help
contributing
changelog
```
