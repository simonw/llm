# Setup

## Installation

Install this tool using `pip`:

    pip install llm

Or using [pipx](https://pypa.github.io/pipx/):

    pipx install llm

## Authentication

Many LLM models require an API key. These API keys can be provided to this tool using several different mechanisms.

### Saving and using stored keys

Keys can be persisted in a file that is used by the tool. This file is called `keys.json` and is located at the path shown when you run the following command:

```
llm keys path
```
On macOS this will be `~/Library/Application Support/io.datasette.llm/keys.json`. On Linux it may be something like `~/.config/io.datasette.llm/keys.json`.

Rather than editing this file directly, you can instead add keys to it using the `llm keys set` command.

To set your OpenAI API key, run the following:

```
llm keys set openai
```
You will be prompted to enter the key like this:
```
% llm keys set openai
Enter key:
```
Enter the key and hit Enter - the key will be saved to your `keys.json` file and automatically used for future command runs:

```
llm "Five ludicrous names for a pet lobster"
```
### Passing keys using the --key option

Keys can be passed directly using the `--key` option, like this:

```
llm "Five names for pet weasels" --key sk-my-key-goes-here
```
You can also pass the alias of a key stored in the `keys.json` file. For example, if you want to maintain a personal API key you could add that like this:
```
llm keys set personal
```
And then use it for prompts like so:

```
llm "Five friendly names for a pet skunk" --key personal
```

### Keys in environment variables

Keys can also be set using an environment variable. These are different for different models.

For OpenAI models the key will be read from the `OPENAI_API_KEY` environment variable.

The environment variable will be used only if no `--key` option is passed to the command.

If no environment variable is found, the tool will fall back to checking `keys.json`.

You can force the tool to use the key from `keys.json` even if an environment variable has also been set using `llm "prompt" --key openai`.
