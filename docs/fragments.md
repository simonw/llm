(fragments)=
# Fragments

LLM prompts can optionally be composed out of **fragments** - reusable pieces of text that are logged just once to the database and can then be attached to multiple prompts.

These are particularly useful when you are working with long context models, which support feeding large amounts of text in as part of your prompt.

Fragments primarily exist to save space in the database, but may be used to support other features such as vendor prompt caching as well.

Fragments can be specified using several different mechanisms:

- URLs to text files online
- Paths to text files on disk
- Aliases that have been attached to a specific fragment
- Hash IDs of stored fragments, where the ID is the SHA256 hash of the fragment content
- Fragments that are provided by custom plugins - these look like `plugin-name:argument`

(fragments-usage)=
## Using fragments in a prompt

Use the `-f/--fragment` option to specify one or more fragments to be used as part of your prompt:

```bash
llm -f https://llm.datasette.io/robots.txt "Explain this robots.txt file in detail"
```
Here we are specifying a fragment using a URL. The contents of that URL will be included in the prompt that is sent to the model, prepended prior to the prompt text.

The `-f` option can be used multiple times to combine together multiple fragments.

Fragments can also be files on disk, for example:
```bash
llm -f setup.py 'extract the metadata'
```
Use `-` to specify a fragment that is read from standard input:
```bash
llm -f - 'extract the metadata' < setup.py
```
This will read the contents of `setup.py` from standard input and use it as a fragment.

Fragments can also be used as part of your system prompt. Use `--sf value` or `--system-fragment value` instead of `-f`.

(fragments-browsing)=
## Browsing fragments

You can view a truncated version of the fragments you have previously stored in your database with the `llm fragments` command:

```bash
llm fragments
```
The output from that command looks like this:

```yaml
- hash: 0d6e368f9bc21f8db78c01e192ecf925841a957d8b991f5bf9f6239aa4d81815
  aliases: []
  datetime_utc: '2025-04-06 07:36:53'
  source: https://raw.githubusercontent.com/simonw/llm-docs/refs/heads/main/llm/0.22.txt
  content: |-
    <documents>
    <document index="1">
    <source>docs/aliases.md</source>
    <document_content>
    (aliases)=
    #...
- hash: 16b686067375182573e2aa16b5bfc1e64d48350232535d06444537e51f1fd60c
  aliases: []
  datetime_utc: '2025-04-06 23:03:47'
  source: simonw/files-to-prompt/pyproject.toml
  content: |-
    [project]
    name = "files-to-prompt"
    version = "0.6"
    description = "Concatenate a directory full of...
```
Those long `hash` values are IDs that can be used to reference a fragment in the future:
```bash
llm -f 16b686067375182573e2aa16b5bfc1e64d48350232535d06444537e51f1fd60c 'Extract metadata'
```
Use `-q searchterm` one or more times to search for fragments that match a specific set of search terms.

To view the full content of a fragment use `llm fragments show`:
```bash
llm fragments show 0d6e368f9bc21f8db78c01e192ecf925841a957d8b991f5bf9f6239aa4d81815
```

(fragments-aliases)=
## Setting aliases for fragments

You can assign aliases to fragments that you use often using the `llm fragments set` command:
```bash
llm fragments set mydocs ./docs.md
```
To remove an alias, use `llm fragments remove`:
```bash
llm fragments remove mydocs
```
You can then use that alias in place of the fragment hash ID:
```bash
llm -f mydocs 'How do I access metadata?'
```
Use `llm fragments --aliases` to see a full list of fragments that have been assigned aliases:
```bash
llm fragments --aliases
```

(fragments-logs)=
## Viewing fragments in your logs

The `llm logs` command lists the fragments that were used for a prompt. By default these are listed as fragment hash IDs, but you can use the `--expand` option to show the full content of each fragment.

This command will show the expanded fragments for your most recent conversation:

```bash
llm logs -c --expand
```
You can filter for logs that used a specific fragment using the `-f/--fragment` option:
```bash
llm logs -c -f 0d6e368f9bc21f8db78c01e192ecf925841a957d8b991f5bf9f6239aa4d81815
```
This accepts URLs, file paths, aliases, and hash IDs.

Multiple `-f` options will return responses that used **all** of the specified fragments.

Fragments are returned by `llm logs --json` as well. By default these are truncated but you can add the `-e/--expand` option to show the full content of each fragment.

```bash
llm logs -c --json --expand
```

(fragments-plugins)=
## Using fragments from plugins

LLM plugins can provide custom fragment loaders which do useful things.

One example is the [llm-fragments-github plugin](https://github.com/simonw/llm-fragments-github). This can convert the file from a public GitHub repository into a list of fragments, allowing you to ask questions about the full repository.

Here's how to try that out:

```bash
llm install llm-fragments-github
llm -f github:simonw/s3-credentials 'Suggest new features for this tool'
```
This plugin turns a single call to `-f github:simonw/s3-credentials` into multiple fragments, one for every text file in the [simonw/s3-credentials](https://github.com/simonw/s3-credentials) GitHub repository.

Running `llm logs -c` will show that this prompt incorporated 26 fragments, one for each file.

Running `llm logs -c --usage --expand` includes token usage information and turns each fragment ID into a full copy of that file. [Here's the output of that command](https://gist.github.com/simonw/c9bbbc5f6560b01f4b7882ac0194fb25).

See the {ref}`register_fragment_loaders() plugin hook <plugin-hooks-register-fragment-loaders>` documentation for details on writing your own custom fragment plugin.
