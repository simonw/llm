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

## Upgrading to the latest version

If you installed using `pip`:
```bash
pip install -U llm
```
For `pipx`:
```bash
pipx upgrade llm
```
For Homebrew:
```bash
brew upgrade llm
```
If the latest version is not yet available on Homebrew you can upgrade like this instead:
```bash
llm install -U llm
```

## Installing plugins

{ref}`plugins` can be used to add support for other language models, including models that can run on your own device.

For example, the [llm-gpt4all](https://github.com/simonw/llm-gpt4all) plugin adds support for 17 new models that can be installed on your own machine. You can install that like so:
```bash
llm install llm-gpt4all
```

(api-keys)=
## API key management

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

You can list the names of keys that have been set using this command:

```bash
llm keys
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

The environment variable will be used if no `--key` option is passed to the command and there is not a key configured in `keys.json`

To use an environment variable in place of the `keys.json` key run the prompt like this:
```bash
llm 'my prompt' --key $OPENAI_API_KEY
```

## Configuration

You can configure LLM in a number of different ways.

### Setting a custom default model

The model used when calling `llm` without the `-m/--model` option defaults to `gpt-3.5-turbo` - the fastest and least expensive OpenAI model, and the same model family that powers ChatGPT.

You can use the `llm models default` command to set a different default model. For GPT-4 (slower and more expensive, but more capable) run this:

```bash
llm models default gpt-4
```
You can view the current model by running this:
```
llm models default
```
Any of the supported aliases for a model can be passed to this command.

### Setting a custom directory location

This tool stores various files - prompt templates, stored keys, preferences, a database of logs - in a directory on your computer.

On macOS this is `~/Library/Application Support/io.datasette.llm/`.

On Linux it may be something like `~/.config/io.datasette.llm/`.

You can set a custom location for this directory by setting the `LLM_USER_PATH` environment variable:

```bash
export LLM_USER_PATH=/path/to/my/custom/directory
```
### Turning SQLite logging on and off

By default, LLM will log every prompt and response you make to a SQLite database - see {ref}`logging` for more details.

You can turn this behavior off by default by running:
```bash
llm logs off
```
Or turn it back on again with:
```
llm logs on
```
Run `llm logs status` to see the current states of the setting.