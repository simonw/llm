(usage)=
# Usage

The command to run a prompt is `llm prompt 'your prompt'`. This is the default command, so you can use `llm 'your prompt'` as a shortcut.

(usage-executing-prompts)=
## Executing a prompt

These examples use the default OpenAI `gpt-3.5-turbo` model, which requires you to first {ref}`set an OpenAI API key <api-keys>`.

You can {ref}`install LLM plugins <installing-plugins>` to use models from other providers, including openly licensed models you can run directly on your own computer.

To run a prompt, streaming tokens as they come in:
```bash
llm 'Ten names for cheesecakes'
```
To disable streaming and only return the response once it has completed:
```bash
llm 'Ten names for cheesecakes' --no-stream
```
To switch from ChatGPT 3.5 (the default) to GPT-4 Turbo:
```bash
llm 'Ten names for cheesecakes' -m gpt-4-turbo
```
You can use `-m 4t` as an even shorter shortcut.

Pass `--model <model name>` to use a different model. Run `llm models` to see a list of available models.

You can also send a prompt to standard input, for example:
```bash
echo 'Ten names for cheesecakes' | llm
```
If you send text to standard input and provide arguments, the resulting prompt will consist of the piped content followed by the arguments:
```bash
cat myscript.py | llm 'explain this code'
```
Will run a prompt of:
```
<contents of myscript.py> explain this code
```
For models that support them, {ref}`system prompts <system-prompts>` are a better tool for this kind of prompting.

Some models support options. You can pass these using `-o/--option name value` - for example, to set the temperature to 1.5 run this:

```bash
llm 'Ten names for cheesecakes' -o temperature 1.5
```

(usage-completion-prompts)=
## Completion prompts

Some models are completion models - rather than being tuned to respond to chat style prompts, they are designed to complete a sentence or paragraph.

An example of this is the `gpt-3.5-turbo-instruct` OpenAI model.

You can prompt that model the same way as the chat models, but be aware that the prompt format that works best is likely to differ.

```bash
llm -m gpt-3.5-turbo-instruct 'Reasons to tame a wild beaver:'
```

(conversation)=
## Continuing a conversation

By default, the tool will start a new conversation each time you run it.

You can opt to continue the previous conversation by passing the `-c/--continue` option:
```bash
llm 'More names' -c
```
This will re-send the prompts and responses for the previous conversation as part of the call to the language model. Note that this can add up quickly in terms of tokens, especially if you are using expensive models.

`--continue` will automatically use the same model as the conversation that you are continuing, even if you omit the `-m/--model` option.

To continue a conversation that is not the most recent one, use the `--cid/--conversation <id>` option:
```bash
llm 'More names' --cid 01h53zma5txeby33t1kbe3xk8q
```
You can find these conversation IDs using the `llm logs` command.

## Using with a shell

To learn more about your computer's operating system based on the output of `uname -a`, run this:
```bash
llm "Tell me about my operating system: $(uname -a)"
```
This pattern of using `$(command)` inside a double quoted string is a useful way to quickly assemble prompts.

(system-prompts)=
## System prompts

You can use `-s/--system '...'` to set a system prompt.
```bash
llm 'SQL to calculate total sales by month' \
  --system 'You are an exaggerated sentient cheesecake that knows SQL and talks about cheesecake a lot'
```
This is useful for piping content to standard input, for example:
```bash
curl -s 'https://simonwillison.net/2023/May/15/per-interpreter-gils/' | \
  llm -s 'Suggest topics for this post as a JSON array'
```
Or to generate a description of changes made to a Git repository since the last commit:
```bash
git diff | llm -s 'Describe these changes'
```
Different models support system prompts in different ways.

The OpenAI models are particularly good at using system prompts as instructions for how they should process additional input sent as part of the regular prompt.

Other models might use system prompts change the default voice and attitude of the model.

System prompts can be saved as {ref}`templates <prompt-templates>` to create reusable tools. For example, you can create a template called `pytest` like this:

```bash
llm -s 'write pytest tests for this code' --save pytest
```
And then use the new template like this:
```bash
cat llm/utils.py | llm -t pytest
```
See {ref}`prompt templates <prompt-templates>` for more.

(usage-chat)=

## Starting an interactive chat

The `llm chat` command starts an ongoing interactive chat with a model.

This is particularly useful for models that run on your own machine, since it saves them from having to be loaded into memory each time a new prompt is added to a conversation.

Run `llm chat`, optionally with a `-m model_id`, to start a chat conversation:

```bash
llm chat -m chatgpt
```
Each chat starts a new conversation. A record of each conversation can be accessed through {ref}`the logs <logs-conversation>`.

You can pass `-c` to start a conversation as a continuation of your most recent prompt. This will automatically use the most recently used model:

```bash
llm chat -c
```

For models that support them, you can pass options using `-o/--option`:
```bash
llm chat -m gpt-4 -o temperature 0.5
```

You can pass a system prompt to be used for your chat conversation:

```bash
llm chat -m gpt-4 -s 'You are a sentient cheesecake'
```
You can also pass {ref}`a template <prompt-templates>` - useful for creating chat personas that you wish to return to.

Here's how to create a template for your GPT-4 powered cheesecake:
```bash
llm --system 'You are a sentient cheesecake' -m gpt-4 --save cheesecake
```
Now you can start a new chat with your cheesecake any time you like using this:
```bash
llm chat -t cheesecake
```
```
Chatting with gpt-4
Type 'exit' or 'quit' to exit
Type '!multi' to enter multiple lines, then '!end' to finish
> who are you?
I am a sentient cheesecake, meaning I am an artificial
intelligence embodied in a dessert form, specifically a
cheesecake. However, I don't consume or prepare foods
like humans do, I communicate, learn and help answer
your queries.
```

Type `quit` or `exit` followed by `<enter>` to end a chat session.

Sometimes you may want to paste multiple lines of text into a chat at once - for example when debugging an error message.

To do that, type `!multi` to start a multi-line input. Type or paste your text, then type `!end` and hit `<enter>` to finish.

If your pasted text might itself contain a `!end` line, you can set a custom delimiter using `!multi abc` followed by `!end abc` at the end:

```
Chatting with gpt-4
Type 'exit' or 'quit' to exit
Type '!multi' to enter multiple lines, then '!end' to finish
> !multi custom-end
 Explain this error:

   File "/opt/homebrew/Caskroom/miniconda/base/lib/python3.10/urllib/request.py", line 1391, in https_open
    return self.do_open(http.client.HTTPSConnection, req,
  File "/opt/homebrew/Caskroom/miniconda/base/lib/python3.10/urllib/request.py", line 1351, in do_open
    raise URLError(err)
urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>

 !end custom-end
```

## Listing available models

The `llm models` command lists every model that can be used with LLM, along with their aliases. This includes models that have been installed using {ref}`plugins <plugins>`.

```bash
llm models
```
Example output:
```
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k)
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
OpenAI Chat: gpt-4-32k (aliases: 4-32k)
PaLM 2: chat-bison-001 (aliases: palm, palm2)
```

Add `--options` to also see documentation for the options supported by each model:
```bash
llm models --options
```
Output:
<!-- [[[cog
from click.testing import CliRunner
from llm.cli import cli
result = CliRunner().invoke(cli, ["models", "list", "--options"])
cog.out("```\n{}\n```".format(result.output))
]]] -->
```
OpenAI Chat: gpt-3.5-turbo (aliases: 3.5, chatgpt)
  temperature: float
    What sampling temperature to use, between 0 and 2. Higher values like
    0.8 will make the output more random, while lower values like 0.2 will
    make it more focused and deterministic.
  max_tokens: int
    Maximum number of tokens to generate.
  top_p: float
    An alternative to sampling with temperature, called nucleus sampling,
    where the model considers the results of the tokens with top_p
    probability mass. So 0.1 means only the tokens comprising the top 10%
    probability mass are considered. Recommended to use top_p or
    temperature but not both.
  frequency_penalty: float
    Number between -2.0 and 2.0. Positive values penalize new tokens based
    on their existing frequency in the text so far, decreasing the model's
    likelihood to repeat the same line verbatim.
  presence_penalty: float
    Number between -2.0 and 2.0. Positive values penalize new tokens based
    on whether they appear in the text so far, increasing the model's
    likelihood to talk about new topics.
  stop: str
    A string where the API will stop generating further tokens.
  logit_bias: dict, str
    Modify the likelihood of specified tokens appearing in the completion.
    Pass a JSON string like '{"1712":-100, "892":-100, "1489":-100}'
  seed: int
    Integer seed to attempt to sample deterministically
OpenAI Chat: gpt-3.5-turbo-16k (aliases: chatgpt-16k, 3.5-16k)
  temperature: float
  max_tokens: int
  top_p: float
  frequency_penalty: float
  presence_penalty: float
  stop: str
  logit_bias: dict, str
  seed: int
OpenAI Chat: gpt-4 (aliases: 4, gpt4)
  temperature: float
  max_tokens: int
  top_p: float
  frequency_penalty: float
  presence_penalty: float
  stop: str
  logit_bias: dict, str
  seed: int
OpenAI Chat: gpt-4-1106-preview (aliases: gpt-4-turbo, 4-turbo, 4t)
  temperature: float
  max_tokens: int
  top_p: float
  frequency_penalty: float
  presence_penalty: float
  stop: str
  logit_bias: dict, str
  seed: int
OpenAI Chat: gpt-4-32k (aliases: 4-32k)
  temperature: float
  max_tokens: int
  top_p: float
  frequency_penalty: float
  presence_penalty: float
  stop: str
  logit_bias: dict, str
  seed: int
OpenAI Completion: gpt-3.5-turbo-instruct (aliases: 3.5-instruct, chatgpt-instruct)
  temperature: float
    What sampling temperature to use, between 0 and 2. Higher values like
    0.8 will make the output more random, while lower values like 0.2 will
    make it more focused and deterministic.
  max_tokens: int
    Maximum number of tokens to generate.
  top_p: float
    An alternative to sampling with temperature, called nucleus sampling,
    where the model considers the results of the tokens with top_p
    probability mass. So 0.1 means only the tokens comprising the top 10%
    probability mass are considered. Recommended to use top_p or
    temperature but not both.
  frequency_penalty: float
    Number between -2.0 and 2.0. Positive values penalize new tokens based
    on their existing frequency in the text so far, decreasing the model's
    likelihood to repeat the same line verbatim.
  presence_penalty: float
    Number between -2.0 and 2.0. Positive values penalize new tokens based
    on whether they appear in the text so far, increasing the model's
    likelihood to talk about new topics.
  stop: str
    A string where the API will stop generating further tokens.
  logit_bias: dict, str
    Modify the likelihood of specified tokens appearing in the completion.
    Pass a JSON string like '{"1712":-100, "892":-100, "1489":-100}'
  seed: int
    Integer seed to attempt to sample deterministically
  logprobs: int
    Include the log probabilities of most likely N per token

```
<!-- [[[end]]] -->

When running a prompt you can pass the full model name or any of the aliases to the `-m/--model` option:
```bash
llm -m chatgpt-16k \
  'As many names for cheesecakes as you can think of, with detailed descriptions'
```
