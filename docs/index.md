# LLM

[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://llm.datasette.io/en/stable/changelog.html)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/master/LICENSE)

A command-line utility for interacting with Large Language Models, such as OpenAI's GPT series.

## Quick start

```bash
# Install LLM
pip install llm
# Or use: brew install simonw/llm/llm

# Paste your OpenAI API key into this:
llm keys set openai

# Run a prompt
llm "Ten fun names for a pet pelican"
```

## Contents

```{toctree}
---
maxdepth: 3
---
setup
usage
templates
logging
plugins
help
contributing
changelog
```
