# Prompt templates

Prompt templates can be created to reuse useful prompts with different input data.

## Getting started

Here's a template for summarizing text:

```yaml
'Summarize this: $input'
```
To create this template with the name `summary` run the following:

```
llm templates edit summary
```
This will open a system default editor.

You can also create a file called `summary.yaml` in the folder shown by runnnig `llm templates path`, for example:
```bash
$ llm templates path
/Users/simon/Library/Application Support/io.datasette.llm/templates
```
You can then use the new template like this:

```
curl -s https://llm.datasette.io/en/latest/ | \
  llm -t summary -m gpt-3.5-turbo-16k
```

## More advanced templates

Templates are YAML files. A template can contain a single string, as shown above, which will then be treated as the prompt.

You can instead set a system prompt using a `system:` key like so:

```yaml
system: Summarize this
```
You can combine system and regular prompts like so:

```yaml
system: You speak like an enthusiastic Victorian explorer
prompt: 'Summarize this: $input'
```
