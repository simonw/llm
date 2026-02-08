# Using LLM with uv

[uv](https://docs.astral.sh/uv/) is a fast Python package installer and resolver. It provides several ways to install and run LLM.

## Installation

To install LLM as a global tool using `uv`:

```bash
uv tool install llm
```

You can now run `llm` from anywhere in your terminal.

### Upgrading

To upgrade to the latest version:

```bash
uv tool upgrade llm
```

## Running without installation (uvx)

You can run LLM without installing it using `uvx`. This creates a temporary virtual environment, runs the command, and then cleans up.

```bash
uvx llm "A joke about a pelican"
```

### Running with plugins

If you want to use a plugin with `uvx`, use the `--with` flag:

```bash
uvx --with llm-anthropic llm -m claude-3.5-sonnet "Hello"
```

You can even specify multiple plugins:

```bash
uvx --with llm-anthropic --with llm-gpt4all llm models
```

## Managing plugins

If you installed LLM via `uv tool install`, you can't use `llm install` to install plugins, because `uv` manages the environment. Instead, use `uv tool inject`:

```bash
uv tool inject llm llm-anthropic llm-gpt4all
```

To list the plugins installed in the `llm` tool environment:

```bash
uv tool list llm
```

## Local Development

If you are developing LLM or a plugin, you can use `uv` to manage your development environment.

### Setting up a development environment

Clone the repository and run:

```bash
uv venv
source .venv/bin/activate # or the equivalent for your shell
uv pip install -e '.[test]'
```

### Running tests

You can run tests using `uv run`:

```bash
uv run pytest
```

Or for a specific test file:

```bash
uv run pytest tests/test_utils.py
```

### Running the development version

To run the version of `llm` in your current directory:

```bash
uv run llm --help
```

## Useful Examples

### One-off prompt with a specific plugin
```bash
uvx --with llm-anthropic llm -m claude-3-opus "Explain quantum entanglement"
```

### Setting up keys via uvx
```bash
uvx llm keys set openai
# Enter your key when prompted
```

### Using LLM in a pipe with uvx
```bash
cat code.py | uvx llm -s "Explain this code"
```

### Injecting multiple plugins at once
```bash
uv tool inject llm llm-anthropic llm-gemini llm-mistral
```
