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
        hyphenated = "-".join(command)
        if hyphenated:
            hyphenated = "-" + hyphenated
        output.append(f"\n(help{hyphenated})=")
        output.append("#" * heading_level + " llm " + " ".join(command) + " --help")
        output.append("```")
        output.append(result.output.replace("Usage: cli", "Usage: llm").strip())
        output.append("```")
    return "\n".join(output)
cog.out(all_help(cli))
]]] -->

(help)=
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
  chat          Hold an ongoing chat with a model.
  collections   View and manage collections of embeddings
  embed         Embed text and store or return the result
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

(help-prompt)=
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

(help-chat)=
### llm chat --help
```
Usage: llm chat [OPTIONS]

  Hold an ongoing chat with a model.

Options:
  -s, --system TEXT            System prompt to use
  -m, --model TEXT             Model to use
  -c, --continue               Continue the most recent conversation.
  --cid, --conversation TEXT   Continue the conversation with the given ID.
  -t, --template TEXT          Template to use
  -p, --param <TEXT TEXT>...   Parameters for template
  -o, --option <TEXT TEXT>...  key/value options for the model
  --no-stream                  Do not stream output
  --key TEXT                   API key to use
  --help                       Show this message and exit.
```

(help-keys)=
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

(help-keys-list)=
#### llm keys list --help
```
Usage: llm keys list [OPTIONS]

  List names of all stored keys

Options:
  --help  Show this message and exit.
```

(help-keys-path)=
#### llm keys path --help
```
Usage: llm keys path [OPTIONS]

  Output the path to the keys.json file

Options:
  --help  Show this message and exit.
```

(help-keys-set)=
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

(help-logs)=
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

(help-logs-path)=
#### llm logs path --help
```
Usage: llm logs path [OPTIONS]

  Output the path to the logs.db file

Options:
  --help  Show this message and exit.
```

(help-logs-status)=
#### llm logs status --help
```
Usage: llm logs status [OPTIONS]

  Show current status of database logging

Options:
  --help  Show this message and exit.
```

(help-logs-on)=
#### llm logs on --help
```
Usage: llm logs on [OPTIONS]

  Turn on logging for all prompts

Options:
  --help  Show this message and exit.
```

(help-logs-off)=
#### llm logs off --help
```
Usage: llm logs off [OPTIONS]

  Turn off logging for all prompts

Options:
  --help  Show this message and exit.
```

(help-logs-list)=
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
  -r, --response              Just output the last response
  -c, --current               Show logs from the current conversation
  --cid, --conversation TEXT  Show logs for this conversation ID
  --json                      Output logs as JSON
  --help                      Show this message and exit.
```

(help-models)=
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

(help-models-list)=
#### llm models list --help
```
Usage: llm models list [OPTIONS]

  List available models

Options:
  --options  Show options for each model, if available
  --help     Show this message and exit.
```

(help-models-default)=
#### llm models default --help
```
Usage: llm models default [OPTIONS] [MODEL]

  Show or set the default model

Options:
  --help  Show this message and exit.
```

(help-templates)=
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

(help-templates-list)=
#### llm templates list --help
```
Usage: llm templates list [OPTIONS]

  List available prompt templates

Options:
  --help  Show this message and exit.
```

(help-templates-show)=
#### llm templates show --help
```
Usage: llm templates show [OPTIONS] NAME

  Show the specified prompt template

Options:
  --help  Show this message and exit.
```

(help-templates-edit)=
#### llm templates edit --help
```
Usage: llm templates edit [OPTIONS] NAME

  Edit the specified prompt template using the default $EDITOR

Options:
  --help  Show this message and exit.
```

(help-templates-path)=
#### llm templates path --help
```
Usage: llm templates path [OPTIONS]

  Output the path to the templates directory

Options:
  --help  Show this message and exit.
```

(help-aliases)=
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

(help-aliases-list)=
#### llm aliases list --help
```
Usage: llm aliases list [OPTIONS]

  List current aliases

Options:
  --json  Output as JSON
  --help  Show this message and exit.
```

(help-aliases-set)=
#### llm aliases set --help
```
Usage: llm aliases set [OPTIONS] ALIAS MODEL_ID

  Set an alias for a model

  Example usage:

      $ llm aliases set turbo gpt-3.5-turbo

Options:
  --help  Show this message and exit.
```

(help-aliases-remove)=
#### llm aliases remove --help
```
Usage: llm aliases remove [OPTIONS] ALIAS

  Remove an alias

  Example usage:

      $ llm aliases remove turbo

Options:
  --help  Show this message and exit.
```

(help-aliases-path)=
#### llm aliases path --help
```
Usage: llm aliases path [OPTIONS]

  Output the path to the aliases.json file

Options:
  --help  Show this message and exit.
```

(help-plugins)=
### llm plugins --help
```
Usage: llm plugins [OPTIONS]

  List installed plugins

Options:
  --all   Include built-in default plugins
  --help  Show this message and exit.
```

(help-install)=
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

(help-uninstall)=
### llm uninstall --help
```
Usage: llm uninstall [OPTIONS] PACKAGES...

  Uninstall Python packages from the LLM environment

Options:
  -y, --yes  Don't ask for confirmation
  --help     Show this message and exit.
```

(help-embed)=
### llm embed --help
```
Usage: llm embed [OPTIONS] [COLLECTION] [ID]

  Embed text and store or return the result

Options:
  -i, --input PATH                File to embed
  -m, --model TEXT                Embedding model to use
  --store                         Store the text itself in the database
  -d, --database FILE
  -c, --content TEXT              Content to embed
  --binary                        Treat input as binary data
  --metadata TEXT                 JSON object metadata to store
  -f, --format [json|blob|base64|hex]
                                  Output format
  --help                          Show this message and exit.
```

(help-embed-multi)=
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
  --encoding TEXT              Encoding to use when reading --files
  --binary                     Treat --files as binary data
  --sql TEXT                   Read input using this SQL query
  --attach <TEXT FILE>...      Additional databases to attach - specify alias
                               and file path
  --batch-size INTEGER         Batch size to use when running embeddings
  --prefix TEXT                Prefix to add to the IDs
  -m, --model TEXT             Embedding model to use
  --store                      Store the text itself in the database
  -d, --database FILE
  --help                       Show this message and exit.
```

(help-similar)=
### llm similar --help
```
Usage: llm similar [OPTIONS] COLLECTION [ID]

  Return top N similar IDs from a collection

  Example usage:

      llm similar my-collection -c "I like cats"

  Or to find content similar to a specific stored ID:

      llm similar my-collection 1234

Options:
  -i, --input PATH      File to embed for comparison
  -c, --content TEXT    Content to embed for comparison
  --binary              Treat input as binary data
  -n, --number INTEGER  Number of results to return
  -d, --database FILE
  --help                Show this message and exit.
```

(help-embed-models)=
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

(help-embed-models-list)=
#### llm embed-models list --help
```
Usage: llm embed-models list [OPTIONS]

  List available embedding models

Options:
  --help  Show this message and exit.
```

(help-embed-models-default)=
#### llm embed-models default --help
```
Usage: llm embed-models default [OPTIONS] [MODEL]

  Show or set the default embedding model

Options:
  --remove-default  Reset to specifying no default model
  --help            Show this message and exit.
```

(help-collections)=
### llm collections --help
```
Usage: llm collections [OPTIONS] COMMAND [ARGS]...

  View and manage collections of embeddings

Options:
  --help  Show this message and exit.

Commands:
  list*   View a list of collections
  delete  Delete the specified collection
  path    Output the path to the embeddings database
```

(help-collections-path)=
#### llm collections path --help
```
Usage: llm collections path [OPTIONS]

  Output the path to the embeddings database

Options:
  --help  Show this message and exit.
```

(help-collections-list)=
#### llm collections list --help
```
Usage: llm collections list [OPTIONS]

  View a list of collections

Options:
  -d, --database FILE  Path to embeddings database
  --json               Output as JSON
  --help               Show this message and exit.
```

(help-collections-delete)=
#### llm collections delete --help
```
Usage: llm collections delete [OPTIONS] COLLECTION

  Delete the specified collection

  Example usage:

      llm collections delete my-collection

Options:
  -d, --database FILE  Path to embeddings database
  --help               Show this message and exit.
```

(help-openai)=
### llm openai --help
```
Usage: llm openai [OPTIONS] COMMAND [ARGS]...

  Commands for working directly with the OpenAI API

Options:
  --help  Show this message and exit.

Commands:
  models  List models available to you from the OpenAI API
```

(help-openai-models)=
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