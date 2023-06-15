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

You can use `--system '...'` to set a system prompt.

    llm 'SQL to calculate total sales by month' \
      --system 'You are an exaggerated sentient cheesecake that knows SQL and talks about cheesecake a lot'

This is useful for piping content to standard input, for example:

    curl -s 'https://simonwillison.net/2023/May/15/per-interpreter-gils/' | \
      llm --system 'Suggest topics for this post as a JSON array'
