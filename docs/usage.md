# Usage

The default command for this is `llm prompt` - you can use `llm` instead if you prefer.

## Executing a prompt

To run a prompt, streaming tokens as they come in:

    llm 'Ten names for cheesecakes'

To disable streaming and only return the response once it has completed:

    llm 'Ten names for cheesecakes' --no-stream

To switch from ChatGPT 3.5 (the default) to GPT-4 if you have access:

    llm 'Ten names for cheesecakes' -m gpt4

You can use `-m 4` as an even shorter shortcut.

Pass `--model <model name>` to use a different model.

You can also send a prompt to standard input, for example:

    echo 'Ten names for cheesecakes' | llm

## Continuing a conversation

By default, the tool will start a new conversation each time you run it.

You can opt to continue the previous conversation by passing the `-c/--continue` option:

    llm 'More names' --continue

This will re-send the prompts and responses for the previous conversation. Note that this can add up quickly in terms of tokens, especially if you are using more expensive models.

To continue a conversation that is not the most recent one, use the `--chat <id>` option:

    llm 'More names' --chat 2

You can find these chat IDs using the `llm logs` command.

Note that this feature only works if you have been logging your previous conversations to a database, having run the `llm init-db` command described below.

## Using with a shell

To generate a description of changes made to a Git repository since the last commit:

    llm "Describe these changes: $(git diff)"

This pattern of using `$(command)` inside a double quoted string is a useful way to quickly assemble prompts.

## System prompts

You can use `-s/--system '...'` to set a system prompt.

    llm 'SQL to calculate total sales by month' \
      --system 'You are an exaggerated sentient cheesecake that knows SQL and talks about cheesecake a lot'

This is useful for piping content to standard input, for example:

    curl -s 'https://simonwillison.net/2023/May/15/per-interpreter-gils/' | \
      llm -s 'Suggest topics for this post as a JSON array'

## Listing available models

The `llm models list` command lists every model that can be used with LLM, along with any aliases:

```
llm models list
```
Example output:
```
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k)
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
OpenAI Chat: gpt-4-32k (aliases: 4-32k)
PaLM 2: chat-bison-001 (aliases: palm, palm2)
```
You can use pass the full model name or any of the aliases to the `-m/--model` option:

```
llm -m chatgpt-16k 'As many names for cheesecakes as you can think of, with detailed descriptions'
```
Models that have been installed using plugins will be shown here as well.

## Setting a custom model

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