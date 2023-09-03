# CLI reference

This page lists the `--help` output for all of the `llm` commands.

<!-- [[[cog
from click.testing import CliRunner
from llm.cli import cli
def all_help(cli):
    "Return all help for Click command and its subcommands"
    # First find all commands and subcommands
    # List will be [["command"], ["command", "subcommand"], ...]
    commands = []
    def find_commands(command, path=None):
        path = path or []
        commands.append(path + [command.name])
        if hasattr(command, 'commands'):
            for subcommand in command.commands.values():
                find_commands(subcommand, path + [command.name])
    find_commands(cli)
    # Remove first item of each list (it is 'cli')
    commands = [command[1:] for command in commands]
    # Now generate help for each one, with appropriate heading level
    output = []
    for command in commands:
        heading_level = len(command) + 2
        result = CliRunner().invoke(cli, command + ["--help"])
        output.append("#" * heading_level + " llm " + " ".join(command) + " --help")
        output.append("```")
        output.append(result.output.replace("Usage: cli", "Usage: llm").strip())
        output.append("```")
    return "\n".join(output)
cog.out(all_help(cli))
]]] -->
## llm  --help
```
Usage: llm [OPTIONS] COMMAND [ARGS]...

  Access large language models from the command-line

  Documentation: https://llm.datasette.io/

  To get started, obtain an OpenAI key and set it like this:

      $ llm keys set openai
      Enter key: ...

  Then execute a prompt like this:

      llm 'Five outrageous names for a pet pelican'

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  prompt*       Execute a prompt
  aliases       Manage model aliases
  embed         Embed text and store or return the result
  embed-db      Manage the embeddings database
  embed-models  Manage available embedding models
  embed-multi   Store embeddings for multiple strings at once
  install       Install packages from PyPI into the same environment as LLM
  keys          Manage stored API keys for different models
  logs          Tools for exploring logged prompts and responses
  models        Manage available models
  openai        Commands for working directly with the OpenAI API
  plugins       List installed plugins
  similar       Return top N similar IDs from a collection
  templates     Manage stored prompt templates
  uninstall     Uninstall Python packages from the LLM environment
```
### llm prompt --help
```
Usage: llm prompt [OPTIONS] [PROMPT]

  Execute a prompt

  Documentation: https://llm.datasette.io/en/stable/usage.html

Options:
  -s, --system TEXT            System prompt to use
  -m, --model TEXT             Model to use
  -o, --option <TEXT TEXT>...  key/value options for the model
  -t, --template TEXT          Template to use
  -p, --param <TEXT TEXT>...   Parameters for template
  --no-stream                  Do not stream output
  -n, --no-log                 Don't log to database
  --log                        Log prompt and response to the database
  -c, --continue               Continue the most recent conversation.
  --cid, --conversation TEXT   Continue the conversation with the given ID.
  --key TEXT                   API key to use
  --save TEXT                  Save prompt with this template name
  --help                       Show this message and exit.
```
### llm keys --help
```
Usage: llm keys [OPTIONS] COMMAND [ARGS]...

  Manage stored API keys for different models

Options:
  --help  Show this message and exit.

Commands:
  list*  List names of all stored keys
  path   Output the path to the keys.json file
  set    Save a key in the keys.json file
```
#### llm keys list --help
```
Usage: llm keys list [OPTIONS]

  List names of all stored keys

Options:
  --help  Show this message and exit.
```
#### llm keys path --help
```
Usage: llm keys path [OPTIONS]

  Output the path to the keys.json file

Options:
  --help  Show this message and exit.
```
#### llm keys set --help
```
Usage: llm keys set [OPTIONS] NAME

  Save a key in the keys.json file

  Example usage:

      $ llm keys set openai
      Enter key: ...

Options:
  --value TEXT  Value to set
  --help        Show this message and exit.
```
### llm logs --help
```
Usage: llm logs [OPTIONS] COMMAND [ARGS]...

  Tools for exploring logged prompts and responses

Options:
  --help  Show this message and exit.

Commands:
  list*   Show recent logged prompts and their responses
  off     Turn off logging for all prompts
  on      Turn on logging for all prompts
  path    Output the path to the logs.db file
  status  Show current status of database logging
```
#### llm logs path --help
```
Usage: llm logs path [OPTIONS]

  Output the path to the logs.db file

Options:
  --help  Show this message and exit.
```
#### llm logs status --help
```
Usage: llm logs status [OPTIONS]

  Show current status of database logging

Options:
  --help  Show this message and exit.
```
#### llm logs on --help
```
Usage: llm logs on [OPTIONS]

  Turn on logging for all prompts

Options:
  --help  Show this message and exit.
```
#### llm logs off --help
```
Usage: llm logs off [OPTIONS]

  Turn off logging for all prompts

Options:
  --help  Show this message and exit.
```
#### llm logs list --help
```
Usage: llm logs list [OPTIONS]

  Show recent logged prompts and their responses

Options:
  -n, --count INTEGER         Number of entries to show - defaults to 3, use 0
                              for all
  -p, --path FILE             Path to log database
  -m, --model TEXT            Filter by model or model alias
  -q, --query TEXT            Search for logs matching this string
  -t, --truncate              Truncate long strings in output
  -c, --current               Show logs from the current conversation
  --cid, --conversation TEXT  Show logs for this conversation ID
  --json                      Output logs as JSON
  --help                      Show this message and exit.
```
### llm models --help
```
Usage: llm models [OPTIONS] COMMAND [ARGS]...

  Manage available models

Options:
  --help  Show this message and exit.

Commands:
  list*    List available models
  default  Show or set the default model
```
#### llm models list --help
```
Usage: llm models list [OPTIONS]

  List available models

Options:
  --options  Show options for each model, if available
  --help     Show this message and exit.
```
#### llm models default --help
```
Usage: llm models default [OPTIONS] [MODEL]

  Show or set the default model

Options:
  --help  Show this message and exit.
```
### llm templates --help
```
Usage: llm templates [OPTIONS] COMMAND [ARGS]...

  Manage stored prompt templates

Options:
  --help  Show this message and exit.

Commands:
  list*  List available prompt templates
  edit   Edit the specified prompt template using the default $EDITOR
  path   Output the path to the templates directory
  show   Show the specified prompt template
```
#### llm templates list --help
```
Usage: llm templates list [OPTIONS]

  List available prompt templates

Options:
  --help  Show this message and exit.
```
#### llm templates show --help
```
Usage: llm templates show [OPTIONS] NAME

  Show the specified prompt template

Options:
  --help  Show this message and exit.
```
#### llm templates edit --help
```
Usage: llm templates edit [OPTIONS] NAME

  Edit the specified prompt template using the default $EDITOR

Options:
  --help  Show this message and exit.
```
#### llm templates path --help
```
Usage: llm templates path [OPTIONS]

  Output the path to the templates directory

Options:
  --help  Show this message and exit.
```
### llm aliases --help
```
Usage: llm aliases [OPTIONS] COMMAND [ARGS]...

  Manage model aliases

Options:
  --help  Show this message and exit.

Commands:
  list*   List current aliases
  path    Output the path to the aliases.json file
  remove  Remove an alias
  set     Set an alias for a model
```
#### llm aliases list --help
```
Usage: llm aliases list [OPTIONS]

  List current aliases

Options:
  --json  Output as JSON
  --help  Show this message and exit.
```
#### llm aliases set --help
```
Usage: llm aliases set [OPTIONS] ALIAS MODEL_ID

  Set an alias for a model

  Example usage:

      $ llm aliases set turbo gpt-3.5-turbo

Options:
  --help  Show this message and exit.
```
#### llm aliases remove --help
```
Usage: llm aliases remove [OPTIONS] ALIAS

  Remove an alias

  Example usage:

      $ llm aliases remove turbo

Options:
  --help  Show this message and exit.
```
#### llm aliases path --help
```
Usage: llm aliases path [OPTIONS]

  Output the path to the aliases.json file

Options:
  --help  Show this message and exit.
```
### llm plugins --help
```
Usage: llm plugins [OPTIONS]

  List installed plugins

Options:
  --help  Show this message and exit.
```
### llm install --help
```
Usage: llm install [OPTIONS] [PACKAGES]...

  Install packages from PyPI into the same environment as LLM

Options:
  -U, --upgrade        Upgrade packages to latest version
  -e, --editable TEXT  Install a project in editable mode from this path
  --force-reinstall    Reinstall all packages even if they are already up-to-
                       date
  --no-cache-dir       Disable the cache
  --help               Show this message and exit.
```
### llm uninstall --help
```
Usage: llm uninstall [OPTIONS] PACKAGES...

  Uninstall Python packages from the LLM environment

Options:
  -y, --yes  Don't ask for confirmation
  --help     Show this message and exit.
```
### llm embed --help
```
Usage: llm embed [OPTIONS] [COLLECTION] [ID]

  Embed text and store or return the result

Options:
  -i, --input FILENAME            File to embed
  -m, --model TEXT                Embedding model to use
  --store                         Store the text itself in the database
  -d, --database FILE
  -c, --content FILE              Content to embed
  --metadata TEXT                 JSON object metadata to store
  -f, --format [json|blob|base64|hex]
                                  Output format
  --help                          Show this message and exit.
```
### llm embed-multi --help
```
Usage: llm embed-multi [OPTIONS] COLLECTION [INPUT_PATH]

  Store embeddings for multiple strings at once

  Input can be CSV, TSV or a JSON list of objects.

  The first column is treated as an ID - all other columns are assumed to be
  text that should be concatenated together in order to calculate the
  embeddings.

  Input data can come from one of three sources:

  1. A CSV, JSON, TSV or JSON-nl file (including on standard input)
  2. A SQL query against a SQLite database
  3. A directory of files

Options:
  --format [json|csv|tsv|nl]   Format of input file - defaults to auto-detect
  --files <DIRECTORY TEXT>...  Embed files in this directory - specify directory
                               and glob pattern
  --sql TEXT                   Read input using this SQL query
  --attach <TEXT FILE>...      Additional databases to attach - specify alias
                               and file path
  --prefix TEXT                Prefix to add to the IDs
  -m, --model TEXT             Embedding model to use
  --store                      Store the text itself in the database
  -d, --database FILE
  --help                       Show this message and exit.
```
### llm similar --help
```
Usage: llm similar [OPTIONS] COLLECTION [ID]

  Return top N similar IDs from a collection

  Example usage:

      llm similar my-collection -c "I like cats"

  Or to find content similar to a specific stored ID:

      llm similar my-collection 1234

Options:
  -i, --input FILENAME  File to embed for comparison
  -c, --content TEXT    Content to embed for comparison
  -n, --number INTEGER  Number of results to return
  -d, --database FILE
  --help                Show this message and exit.
```
### llm embed-models --help
```
Usage: llm embed-models [OPTIONS] COMMAND [ARGS]...

  Manage available embedding models

Options:
  --help  Show this message and exit.

Commands:
  list*    List available embedding models
  default  Show or set the default embedding model
```
#### llm embed-models list --help
```
Usage: llm embed-models list [OPTIONS]

  List available embedding models

Options:
  --help  Show this message and exit.
```
#### llm embed-models default --help
```
Usage: llm embed-models default [OPTIONS] [MODEL]

  Show or set the default embedding model

Options:
  --help  Show this message and exit.
```
### llm embed-db --help
```
Usage: llm embed-db [OPTIONS] COMMAND [ARGS]...

  Manage the embeddings database

Options:
  --help  Show this message and exit.

Commands:
  collections        Output the path to the embeddings database
  delete-collection  Delete the specified collection
  path               Output the path to the embeddings database
```
#### llm embed-db path --help
```
Usage: llm embed-db path [OPTIONS]

  Output the path to the embeddings database

Options:
  --help  Show this message and exit.
```
#### llm embed-db collections --help
```
Usage: llm embed-db collections [OPTIONS]

  Output the path to the embeddings database

Options:
  -d, --database FILE  Path to embeddings database
  --json               Output as JSON
  --help               Show this message and exit.
```
#### llm embed-db delete-collection --help
```
Usage: llm embed-db delete-collection [OPTIONS] COLLECTION

  Delete the specified collection

  Example usage:

      llm embed-db delete-collection my-collection

Options:
  -d, --database FILE  Path to embeddings database
  --help               Show this message and exit.
```
### llm openai --help
```
Usage: llm openai [OPTIONS] COMMAND [ARGS]...

  Commands for working directly with the OpenAI API

Options:
  --help  Show this message and exit.

Commands:
  models  List models available to you from the OpenAI API
```
#### llm openai models --help
```
Usage: llm openai models [OPTIONS]

  List models available to you from the OpenAI API

Options:
  --json      Output as JSON
  --key TEXT  OpenAI API key
  --help      Show this message and exit.
```
<!-- [[[end]]] -->