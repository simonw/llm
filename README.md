# LLM

[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Documentation](https://readthedocs.org/projects/llm/badge/?version=latest)](https://llm.datasette.io/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/823971286308356157?label=discord)](https://datasette.io/discord-llm)
[![Homebrew](https://img.shields.io/homebrew/installs/dy/llm?color=yellow&label=homebrew&logo=homebrew)](https://formulae.brew.sh/formula/llm)

A CLI utility and Python library for interacting with Large Language Models, both via remote APIs and models that can be installed and run on your own machine.

[Run prompts from the command-line](https://llm.datasette.io/en/stable/usage.html#executing-a-prompt), [store the results in SQLite](https://llm.datasette.io/en/stable/logging.html), [generate embeddings](https://llm.datasette.io/en/stable/embeddings/index.html) and more.

Consult the **[LLM plugins directory](https://llm.datasette.io/en/stable/plugins/directory.html)** for plugins that provide access to remote and local models.

Full documentation: **[llm.datasette.io](https://llm.datasette.io/)**

Background on this project:
- [llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/)
- [The LLM CLI tool now supports self-hosted language models via plugins](https://simonwillison.net/2023/Jul/12/llm/)
- [Accessing Llama 2 from the command-line with the llm-replicate plugin](https://simonwillison.net/2023/Jul/18/accessing-llama-2/)
- [Run Llama 2 on your own Mac using LLM and Homebrew](https://simonwillison.net/2023/Aug/1/llama-2-mac/)
- [Catching up on the weird world of LLMs](https://simonwillison.net/2023/Aug/3/weird-world-of-llms/)
- [LLM now provides tools for working with embeddings](https://simonwillison.net/2023/Sep/4/llm-embeddings/)
- [Build an image search engine with llm-clip, chat with models with llm chat](https://simonwillison.net/2023/Sep/12/llm-clip-and-chat/)
- [Many options for running Mistral models in your terminal using LLM](https://simonwillison.net/2023/Dec/18/mistral/)

## Installation

Install this tool using `pip`:
```bash
pip install llm
```
Or using [Homebrew](https://brew.sh/):
```bash
brew install llm
```
[Detailed installation instructions](https://llm.datasette.io/en/stable/setup.html).

## Getting started

If you have an [OpenAI API key](https://platform.openai.com/api-keys) you can get started using the OpenAI models right away.

As an alternative to OpenAI, you can [install plugins](https://llm.datasette.io/en/stable/plugins/installing-plugins.html) to access models by other providers, including models that can be installed and run on your own device.

Save your OpenAI API key like this:

```bash
llm keys set openai
```
This will prompt you for your key like so:
```
Enter key: <paste here>
```
Now that you've saved a key you can run a prompt like this:
```bash
llm "Five cute names for a pet penguin"
```
```
1. Waddles
2. Pebbles
3. Bubbles
4. Flappy
5. Chilly
```
Read the [usage instructions](https://llm.datasette.io/en/stable/usage.html) for more.

## Installing a model that runs on your own machine

[LLM plugins](https://llm.datasette.io/en/stable/plugins/index.html) can add support for alternative models, including models that run on your own machine.

To download and run Mistral 7B Instruct locally, you can install the [llm-gpt4all](https://github.com/simonw/llm-gpt4all) plugin:
```bash
llm install llm-gpt4all
```
Then run this command to see which models it makes available:
```bash
llm models
```
```
gpt4all: all-MiniLM-L6-v2-f16 - SBert, 43.76MB download, needs 1GB RAM
gpt4all: orca-mini-3b-gguf2-q4_0 - Mini Orca (Small), 1.84GB download, needs 4GB RAM
gpt4all: mistral-7b-instruct-v0 - Mistral Instruct, 3.83GB download, needs 8GB RAM
...
```
Each model file will be downloaded once the first time you use it. Try Mistral out like this:
```bash
llm -m mistral-7b-instruct-v0 'difference between a pelican and a walrus'
```
You can also start a chat session with the model using the `llm chat` command:
```bash
llm chat -m mistral-7b-instruct-v0
```
```
Chatting with mistral-7b-instruct-v0
Type 'exit' or 'quit' to exit
Type '!multi' to enter multiple lines, then '!end' to finish
> 
```

## Using a system prompt

You can use the `-s/--system` option to set a system prompt, providing instructions for processing other input to the tool.

To describe how the code in a file works, try this:

```bash
cat mycode.py | llm -s "Explain this code"
```

## Help

For help, run:

    llm --help

You can also use:

    python -m llm --help
