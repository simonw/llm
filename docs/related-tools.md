(related-tools)=
# Related tools

The following tools are designed to be used with LLM:

## strip-tags

[strip-tags](https://github.com/simonw/strip-tags) is a command for stripping tags from HTML. This is useful when working with LLMs because HTML tags can use up a lot of your token budget.

Here's how to summarize the front page of the New York Times, by both stripping tags and filtering to just the elements with `class="story-wrapper"`:

```bash
curl -s https://www.nytimes.com/ \
  | strip-tags .story-wrapper \
  | llm -s 'summarize the news'
```

[llm, ttok and strip-tags—CLI tools for working with ChatGPT and other LLMs](https://simonwillison.net/2023/May/18/cli-tools-for-llms/) describes ways to use `strip-tags` in more detail.

## ttok

[ttok](https://github.com/simon/ttok) is a command-line tool for counting OpenAI tokens. You can use it to check if input is likely to fit in the token limit for GPT 3.5 or GPT4:

```bash
cat my-file.txt | ttok
```
```
125
```
It can also truncate input down to a desired number of tokens:
```bash
ttok This is too many tokens -t 3
```
```
This is too
```
This is useful for truncating a large document down to a size where it can be processed by an LLM.

## symbex

[symbex](https://github.com/simonw/symbex) is a tool for searching for symbols in Python codebases. It's useful for extracting just the code for a specific problem and then piping that into LLM for explanation, refactoring or other tasks.

Here's how to use it to find all functions that match `test*csv*` and use those to guess what the software under test does:

```bash
symbex 'test*csv*' | \
  llm --system 'based on these tests guess what this tool does'
```
For more examples see [symbex: search Python code for functions and classes, then pipe them into a LLM](https://simonwillison.net/2023/Jun/18/symbex/).