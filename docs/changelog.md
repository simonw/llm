# Changelog

## Unreleased

- `llm "prompt" --save template` option for saving a prompt directly to a template. [#55](https://github.com/simonw/llm/issues/55)
- Prompt templates can now specify {ref}`default values <prompt-default-parameters>` for parameters. Thanks,  Chris Mungall. [#57](https://github.com/simonw/llm/pull/57)

(v0_4_1)=
## 0.4.1 (2023-06-17)

- LLM can now be installed using Homebrew: `brew install simonw/llm/llm`. [#50](https://github.com/simonw/llm/issues/50)
- `llm` is now styled LLM in the documentation. [#45](https://github.com/simonw/llm/issues/45)
- Examples in documentation now include a copy button. [#43](https://github.com/simonw/llm/issues/43)
- `llm templates` command no longer has its display disrupted by newlines. [#42](https://github.com/simonw/llm/issues/42)
- `llm templates` command now includes system prompt, if set. [#44](https://github.com/simonw/llm/issues/44)

(v0_4)=
## 0.4 (2023-06-17)

### Prompt templates

{ref}`prompt-templates` is a new feature that allows prompts to be saved as templates and re-used with different variables.

Templates can be created using the `llm templates edit` command:

```bash
llm templates edit summarize
```
Templates are YAML - the following template defines summarization using a system prompt:

```yaml
system: Summarize this text
```
The template can then be executed like this:
```bash
cat myfile.txt | llm -t summarize
```
Templates can include both system prompts, regular prompts and indicate the model they should use. They can reference variables such as `$input` for content piped to the tool, or other variables that are passed using the new `-p/--param` option.

This example adds a `voice` parameter:

```yaml
system: Summarize this text in the voice of $voice
```
Then to run it (via [strip-tags](https://github.com/simonw/strip-tags) to remove HTML tags from the input):
```bash
curl -s 'https://til.simonwillison.net/macos/imovie-slides-and-audio' | \
  strip-tags -m | llm -t summarize -p voice GlaDOS
```
Example output:

> My previous test subject seemed to have learned something new about iMovie. They exported keynote slides as individual images [...] Quite impressive for a human.

The {ref}`prompt-templates` documentation provides more detailed examples.

### Continue previous chat

You can now use `llm` to continue a previous conversation with the OpenAI chat models (`gpt-3.5-turbo` and `gpt-4`). This will include your previous prompts and responses in the prompt sent to the API, allowing the model to continue within the same context.

Use the new `-c/--continue` option to continue from the previous message thread:

```bash
llm "Pretend to be a witty gerbil, say hi briefly"
```
> Greetings, dear human! I am a clever gerbil, ready to entertain you with my quick wit and endless energy.
```bash
llm "What do you think of snacks?" -c
```
> Oh, how I adore snacks, dear human! Crunchy carrot sticks, sweet apple slices, and chewy yogurt drops are some of my favorite treats. I could nibble on them all day long!

The `-c` option will continue from the most recent logged message.

To continue a different chat, pass an integer ID to the `--chat` option. This should be the ID of a previously logged message. You can find these IDs using the `llm logs` command.

Thanks [Amjith Ramanujam](https://github.com/amjith) for contributing to this feature. [#6](https://github.com/simonw/llm/issues/6)

### New mechanism for storing API keys

API keys for language models such as those by OpenAI can now be saved using the new `llm keys` family of commands.

To set the default key to be used for the OpenAI APIs, run this:

```bash
llm keys set openai
```
Then paste in your API key.

Keys can also be passed using the new `--key` command line option - this can be a full key or the alias of a key that has been previously stored.

See link-to-docs for more. [#13](https://github.com/simonw/llm/issues/13)

### New location for the logs.db database

The `logs.db` database that stores a history of executed prompts no longer lives at `~/.llm/log.db` - it can now be found in a location that better fits the host operating system, which can be seen using:

```bash
llm logs path
```
On macOS this is `~/Library/Application Support/io.datasette.llm/logs.db`.

To open that database using Datasette, run this:

```bash
datasette "$(llm logs path)"
```
You can upgrade your existing installation by copying your database to the new location like this:
```bash
cp ~/.llm/log.db "$(llm logs path)"
rm -rf ~/.llm # To tidy up the now obsolete directory
```
The database schema has changed, and will be updated automatically the first time you run the command.

That schema is [included in the documentation](https://llm.datasette.io/en/stable/logging.html#sql-schema). [#35](https://github.com/simonw/llm/issues/35)

### Other changes

- New `llm logs --truncate` option (shortcut `-t`) which truncates the displayed prompts to make the log output easier to read. [#16](https://github.com/simonw/llm/issues/16)
- Documentation now spans multiple pages and lives at <https://llm.datasette.io/> [#21](https://github.com/simonw/llm/issues/21)
- Default `llm chatgpt` command has been renamed to `llm prompt`. [#17](https://github.com/simonw/llm/issues/17)
- Removed `--code` option in favour of new prompt templates mechanism. [#24](https://github.com/simonw/llm/issues/24)
- Responses are now streamed by default, if the model supports streaming. The `-s/--stream` option has been removed. A new `--no-stream` option can be used to opt-out of streaming.  [#25](https://github.com/simonw/llm/issues/25)
- The `-4/--gpt4` option has been removed in favour of `-m 4` or `-m gpt4`, using a new mechanism that allows models to have additional short names.
- The new `gpt-3.5-turbo-16k` model with a 16,000 token context length can now also be accessed using `-m chatgpt-16k` or `-m 3.5-16k`. Thanks, Benjamin Kirkbride. [#37](https://github.com/simonw/llm/issues/37)
- Improved display of error messages from OpenAI. [#15](https://github.com/simonw/llm/issues/15)

(v0_3)=
## 0.3 (2023-05-17)

- `llm logs` command for browsing logs of previously executed completions. [#3](https://github.com/simonw/llm/issues/3)
- `llm "Python code to output factorial 10" --code` option which sets a system prompt designed to encourage code to be output without any additional explanatory text. [#5](https://github.com/simonw/llm/issues/5)
- Tool can now accept a prompt piped directly to standard input. [#11](https://github.com/simonw/llm/issues/11)

(v0_2)=
## 0.2 (2023-04-01)

- If a SQLite database exists in `~/.llm/log.db` all prompts and responses are logged to that file. The `llm init-db` command can be used to create this file. [#2](https://github.com/simonw/llm/issues/2)

(v0_1)=
## 0.1 (2023-04-01)

- Initial prototype release. [#1](https://github.com/simonw/llm/issues/1)
