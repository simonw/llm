# LLM

[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/main/LICENSE)
[![Discord](https://img.shields.io/discord/823971286308356157?label=discord)](https://datasette.io/discord-llm)

A command-line utility for interacting with Large Language Models, such as OpenAI's GPT series.

## Quick start

You'll need an [OpenAI API key](https://platform.openai.com/account/api-keys) for this:

```bash
# Install LLM
pip install llm
# Or use: brew install simonw/llm/llm

# Paste your OpenAI API key into this:
llm keys set openai

# Run a prompt
llm "Ten fun names for a pet pelican"

# Run a system prompt against a file
cat myfile.py | llm -s "Explain this code"
```

You can also [install plugins](https://github.com/simonw/llm-plugins) to access models by other providers, including models that can be installed and run on your own device.


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
