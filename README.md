# llm

[![PyPI](https://img.shields.io/pypi/v/llm.svg)](https://pypi.org/project/llm/)
[![Documentation](https://readthedocs.org/projects/llm/badge/?version=latest)](https://llm.datasette.io/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm?include_prereleases&label=changelog)](https://github.com/simonw/llm/releases)
[![Tests](https://github.com/simonw/llm/workflows/Test/badge.svg)](https://github.com/simonw/llm/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm/blob/master/LICENSE)

Access large language models from the command-line

Full documentation: **[llm.datasette.io](https://llm.datasette.io/)**

See [llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/) for more on this project.

## Installation

Install this tool using `pip`:

    pip install llm

[Detailed installation instructions](https://llm.datasette.io/en/stable/setup.html).

## Getting started

First, create an OpenAI API key and save it to the tool like this:

```
llm keys set openai
```
This will prompt you for your key like so:
```
$ llm keys set openai
Enter key:
```

Now that you've saved a key you can run a prompt like this:

```
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

## Help

For help, run:

    llm --help

You can also use:

    python -m llm --help
