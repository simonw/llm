# LLM

[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/823971286308356157?label=discord)](https://datasette.io/discord-llm)

A CLI utility and Python library for interacting with Large Language Models, including OpenAI, PaLM and local models installed on your own machine.

Background on this project:
- [llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/)
- [The LLM CLI tool now supports self-hosted language models via plugins](https://simonwillison.net/2023/Jul/12/llm/)

## Quick start

First, install LLM using `pip` or Homebrew:

```bash
# Install LLM
pip install llm
# Or use: brew install simonw/llm/llm
```
If you have an [OpenAI API key](https://platform.openai.com/account/api-keys) key you can run this:
```bash
# Paste your OpenAI API key into this
llm keys set openai

# Run a prompt
llm "Ten fun names for a pet pelican"

# Run a system prompt against a file
cat myfile.py | llm -s "Explain this code"
```
Or you can {ref}`install a plugin <installing-plugins>` and use models that can run on your local device:
```bash
# Install the plugin
llm install llm-gpt4all

# Download and run a prompt against the Vicuna model
llm -m ggml-vicuna-7b-1 'What is the capital of France?'
```

## Contents

```{toctree}
---
maxdepth: 3
---
setup
usage
python-api
templates
logging
plugins/index
help
contributing
changelog
```
