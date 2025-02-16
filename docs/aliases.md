(aliases)=
# Model aliases

LLM supports model aliases, which allow you to refer to a model by a short name instead of its full ID.

## Listing aliases

To list current aliases, run this:

```bash
llm aliases
```
Example output:

<!-- [[[cog
from click.testing import CliRunner
from llm.cli import cli
result = CliRunner().invoke(cli, ["aliases", "list"])
cog.out("```\n{}```".format(result.output))
]]] -->
```
4o                  : gpt-4o
chatgpt-4o          : chatgpt-4o-latest
4o-mini             : gpt-4o-mini
3.5                 : gpt-3.5-turbo
chatgpt             : gpt-3.5-turbo
chatgpt-16k         : gpt-3.5-turbo-16k
3.5-16k             : gpt-3.5-turbo-16k
4                   : gpt-4
gpt4                : gpt-4
4-32k               : gpt-4-32k
gpt-4-turbo-preview : gpt-4-turbo
4-turbo             : gpt-4-turbo
4t                  : gpt-4-turbo
3.5-instruct        : gpt-3.5-turbo-instruct
chatgpt-instruct    : gpt-3.5-turbo-instruct
ada                 : text-embedding-ada-002 (embedding)
ada-002             : text-embedding-ada-002 (embedding)
3-small             : text-embedding-3-small (embedding)
3-large             : text-embedding-3-large (embedding)
3-small-512         : text-embedding-3-small-512 (embedding)
3-large-256         : text-embedding-3-large-256 (embedding)
3-large-1024        : text-embedding-3-large-1024 (embedding)
```
<!-- [[[end]]] -->

Add `--json` to get that list back as JSON:

```bash
llm aliases list --json
```
Example output:
```json
{
    "3.5": "gpt-3.5-turbo",
    "chatgpt": "gpt-3.5-turbo",
    "4": "gpt-4",
    "gpt4": "gpt-4",
    "ada": "ada-002"
}
```

## Adding a new alias

The `llm aliases set <alias> <model-id>` command can be used to add a new alias:

```bash
llm aliases set mini gpt-4o-mini
```
You can also pass one or more `-q search` options to set an alias on the first model matching those search terms:
```bash
llm aliases set mini -q 4o -q mini
```
Now you can run the `gpt-4o-mini` model using the `mini` alias like this:
```bash
llm -m mini 'An epic Greek-style saga about a cheesecake that builds a SQL database from scratch'
```
Aliases can be set for both regular models and {ref}`embedding models <embeddings>` using the same command. To set an alias of `oai` for the OpenAI `ada-002` embedding model use this:
```bash
llm aliases set oai ada-002
```
Now you can embed a string using that model like so:
```bash
llm embed -c 'hello world' -m oai
```
Output:
```
[-0.014945968054234982, 0.0014304015785455704, ...]
```

## Removing an alias

The `llm aliases remove <alias>` command will remove the specified alias:

```bash
llm aliases remove mini
```

## Viewing the aliases file

Aliases are stored in an `aliases.json` file in the LLM configuration directory.

To see the path to that file, run this:

```bash
llm aliases path
```
To view the content of that file, run this:

```bash
cat "$(llm aliases path)"
```