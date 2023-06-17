# Setup

## Installation

Install this tool using `pip`:
```bash
pip install llm
```
Or using [pipx](https://pypa.github.io/pipx/):
```bash
pipx install llm
```
## Authentication

Many LLM models require an API key. These API keys can be provided to this tool using several different mechanisms.

You can obtain an API key for OpenAI's language models from [the API keys page](https://platform.openai.com/account/api-keys) on their site.

### Saving and using stored keys

The easiest way to store an API key is to use the `llm keys set` command:

```bash
llm keys set openai
```
You will be prompted to enter the key like this:
```
% llm keys set openai
Enter key:
```
Once stored, this key will be automatically used for subsequent calls to the API:

```bash
llm "Five ludicrous names for a pet lobster"
```
Keys that are stored in this way live in a file called `keys.json`. This file is located at the path shown when you run the following command:

```bash
llm keys path
```
On macOS this will be `~/Library/Application Support/io.datasette.llm/keys.json`. On Linux it may be something like `~/.config/io.datasette.llm/keys.json`.

### Passing keys using the --key option

Keys can be passed directly using the `--key` option, like this:

```bash
llm "Five names for pet weasels" --key sk-my-key-goes-here
```
You can also pass the alias of a key stored in the `keys.json` file. For example, if you want to maintain a personal API key you could add that like this:
```bash
llm keys set personal
```
And then use it for prompts like so:

```bash
llm "Five friendly names for a pet skunk" --key personal
```

### Keys in environment variables

Keys can also be set using an environment variable. These are different for different models.

For OpenAI models the key will be read from the `OPENAI_API_KEY` environment variable.

The environment variable will be used only if no `--key` option is passed to the command.

If no environment variable is found, the tool will fall back to checking `keys.json`.

You can force the tool to use the key from `keys.json` even if an environment variable has also been set using `llm "prompt" --key openai`.
