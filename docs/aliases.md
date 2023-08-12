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
3.5         : gpt-3.5-turbo
chatgpt     : gpt-3.5-turbo
chatgpt-16k : gpt-3.5-turbo-16k
3.5-16k     : gpt-3.5-turbo-16k
4           : gpt-4
gpt4        : gpt-4
4-32k       : gpt-4-32k
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
    "chatgpt-16k": "gpt-3.5-turbo-16k",
    "3.5-16k": "gpt-3.5-turbo-16k",
    "4": "gpt-4",
    "gpt4": "gpt-4",
    "4-32k": "gpt-4-32k"
}
```
