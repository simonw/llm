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

  Access Large Language Models from the command-line

  Documentation: https://llm.datasette.io/

  LLM can run models from many different providers. Consult the plugin directory
  for a list of available models:

  https://llm.datasette.io/en/stable/plugins/directory.html

  To get started with OpenAI, obtain an API key from them and:

      $ llm keys set openai
      Enter key: ...

  Then execute a prompt like this:

      llm 'Five outrageous names for a pet pelican'

  For a full list of prompting options run:

      llm prompt --help

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
  embed-multi   Store embeddings for multiple strings at once in the...
  fragments     Manage fragments that are stored in the database
  install       Install packages from PyPI into the same environment as LLM
  keys          Manage stored API keys for different models
  logs          Tools for exploring logged prompts and responses
  models        Manage available models
  openai        Commands for working directly with the OpenAI API
  plugins       List installed plugins
  schemas       Manage stored schemas
  similar       Return top N similar IDs from a collection using cosine...
  templates     Manage stored prompt templates
  uninstall     Uninstall Python packages from the LLM environment
```

(help-prompt)=
### llm prompt --help
```
Usage: llm prompt [OPTIONS] [PROMPT]

  Execute a prompt

  Documentation: https://llm.datasette.io/en/stable/usage.html

  Examples:

      llm 'Capital of France?'
      llm 'Capital of France?' -m gpt-4o
      llm 'Capital of France?' -s 'answer in Spanish'

  Multi-modal models can be called with attachments like this:

      llm 'Extract text from this image' -a image.jpg
      llm 'Describe' -a https://static.simonwillison.net/static/2024/pelicans.jpg
      cat image | llm 'describe image' -a -
      # With an explicit mimetype:
      cat image | llm 'describe image' --at - image/jpeg

  The -x/--extract option returns just the content of the first ``` fenced code
  block, if one is present. If none are present it returns the full response.

      llm 'JavaScript function for reversing a string' -x

Options:
  -s, --system TEXT               System prompt to use
  -m, --model TEXT                Model to use
  -d, --database FILE             Path to log database
  -q, --query TEXT                Use first model matching these strings
  -a, --attachment ATTACHMENT     Attachment path or URL or -
  --at, --attachment-type <TEXT TEXT>...
                                  Attachment with explicit mimetype
  -o, --option <TEXT TEXT>...     key/value options for the model
  --schema TEXT                   JSON schema, filepath or ID
  --schema-multi TEXT             JSON schema to use for multiple results
  -f, --fragment TEXT             Fragment (alias, URL, hash or file path) to
                                  add to the prompt
  --sf, --system-fragment TEXT    Fragment to add to system prompt
  -t, --template TEXT             Template to use
  -p, --param <TEXT TEXT>...      Parameters for template
  --no-stream                     Do not stream output
  -n, --no-log                    Don't log to database
  --log                           Log prompt and response to the database
  -c, --continue                  Continue the most recent conversation.
  --cid, --conversation TEXT      Continue the conversation with the given ID.
  --key TEXT                      API key to use
  --save TEXT                     Save prompt with this template name
  --async                         Run prompt asynchronously
  -u, --usage                     Show token usage
  -x, --extract                   Extract first fenced code block
  --xl, --extract-last            Extract last fenced code block
  --help                          Show this message and exit.
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
  get    Return the value of a stored key
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

(help-keys-get)=
#### llm keys get --help
```
Usage: llm keys get [OPTIONS] NAME

  Return the value of a stored key

  Example usage:

      export OPENAI_API_KEY=$(llm keys get openai)

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
  -d, --database FILE         Path to log database
  -m, --model TEXT            Filter by model or model alias
  -q, --query TEXT            Search for logs matching this string
  -f, --fragment TEXT         Filter for prompts using these fragments
  --schema TEXT               JSON schema, filepath or ID
  --schema-multi TEXT         JSON schema used for multiple results
  --data                      Output newline-delimited JSON data for schema
  --data-array                Output JSON array of data for schema
  --data-key TEXT             Return JSON objects from array in this key
  --data-ids                  Attach corresponding IDs to JSON objects
  -t, --truncate              Truncate long strings in output
  -s, --short                 Shorter YAML output with truncated prompts
  -u, --usage                 Include token usage
  -r, --response              Just output the last response
  -x, --extract               Extract first fenced code block
  --xl, --extract-last        Extract last fenced code block
  -c, --current               Show logs from the current conversation
  --cid, --conversation TEXT  Show logs for this conversation ID
  --id-gt TEXT                Return responses with ID > this
  --id-gte TEXT               Return responses with ID >= this
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
  options  Manage default options for models
```

(help-models-list)=
#### llm models list --help
```
Usage: llm models list [OPTIONS]

  List available models

Options:
  --options         Show options for each model, if available
  --async           List async models
  --schemas         List models that support schemas
  -q, --query TEXT  Search for models matching these strings
  -m, --model TEXT  Specific model IDs
  --help            Show this message and exit.
```

(help-models-default)=
#### llm models default --help
```
Usage: llm models default [OPTIONS] [MODEL]

  Show or set the default model

Options:
  --help  Show this message and exit.
```

(help-models-options)=
#### llm models options --help
```
Usage: llm models options [OPTIONS] COMMAND [ARGS]...

  Manage default options for models

Options:
  --help  Show this message and exit.

Commands:
  list*  List default options for all models
  clear  Clear default option(s) for a model
  set    Set a default option for a model
  show   List default options set for a specific model
```

(help-models-options-list)=
##### llm models options list --help
```
Usage: llm models options list [OPTIONS]

  List default options for all models

  Example usage:

      llm models options list

Options:
  --help  Show this message and exit.
```

(help-models-options-show)=
##### llm models options show --help
```
Usage: llm models options show [OPTIONS] MODEL

  List default options set for a specific model

  Example usage:

      llm models options show gpt-4o

Options:
  --help  Show this message and exit.
```

(help-models-options-set)=
##### llm models options set --help
```
Usage: llm models options set [OPTIONS] MODEL KEY VALUE

  Set a default option for a model

  Example usage:

      llm models options set gpt-4o temperature 0.5

Options:
  --help  Show this message and exit.
```

(help-models-options-clear)=
##### llm models options clear --help
```
Usage: llm models options clear [OPTIONS] MODEL [KEY]

  Clear default option(s) for a model

  Example usage:

      llm models options clear gpt-4o
      # Or for a single option
      llm models options clear gpt-4o temperature

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
  list*    List available prompt templates
  edit     Edit the specified prompt template using the default $EDITOR
  loaders  Show template loaders registered by plugins
  path     Output the path to the templates directory
  show     Show the specified prompt template
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

(help-templates-loaders)=
#### llm templates loaders --help
```
Usage: llm templates loaders [OPTIONS]

  Show template loaders registered by plugins

Options:
  --help  Show this message and exit.
```

(help-schemas)=
### llm schemas --help
```
Usage: llm schemas [OPTIONS] COMMAND [ARGS]...

  Manage stored schemas

Options:
  --help  Show this message and exit.

Commands:
  list*  List stored schemas
  dsl    Convert LLM's schema DSL to a JSON schema
  show   Show a stored schema
```

(help-schemas-list)=
#### llm schemas list --help
```
Usage: llm schemas list [OPTIONS]

  List stored schemas

Options:
  -d, --database FILE  Path to log database
  -q, --query TEXT     Search for schemas matching this string
  --full               Output full schema contents
  --help               Show this message and exit.
```

(help-schemas-show)=
#### llm schemas show --help
```
Usage: llm schemas show [OPTIONS] SCHEMA_ID

  Show a stored schema

Options:
  -d, --database FILE  Path to log database
  --help               Show this message and exit.
```

(help-schemas-dsl)=
#### llm schemas dsl --help
```
Usage: llm schemas dsl [OPTIONS] INPUT

  Convert LLM's schema DSL to a JSON schema

      llm schema dsl 'name, age int, bio: their bio'

Options:
  --multi  Wrap in an array
  --help   Show this message and exit.
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
Usage: llm aliases set [OPTIONS] ALIAS [MODEL_ID]

  Set an alias for a model

  Example usage:

      llm aliases set mini gpt-4o-mini

  Alternatively you can omit the model ID and specify one or more -q options.
  The first model matching all of those query strings will be used.

      llm aliases set mini -q 4o -q mini

Options:
  -q, --query TEXT  Set alias for model matching these strings
  --help            Show this message and exit.
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

(help-fragments)=
### llm fragments --help
```
Usage: llm fragments [OPTIONS] COMMAND [ARGS]...

  Manage fragments that are stored in the database

  Fragments are reusable snippets of text that are shared across multiple
  prompts.

Options:
  --help  Show this message and exit.

Commands:
  list*   List current fragments
  remove  Remove a fragment alias
  set     Set an alias for a fragment
  show    Display the fragment stored under an alias or hash
```

(help-fragments-list)=
#### llm fragments list --help
```
Usage: llm fragments list [OPTIONS]

  List current fragments

Options:
  -q, --query TEXT  Search for fragments matching these strings
  --json            Output as JSON
  --help            Show this message and exit.
```

(help-fragments-set)=
#### llm fragments set --help
```
Usage: llm fragments set [OPTIONS] ALIAS FRAGMENT

  Set an alias for a fragment

  Accepts an alias and a file path, URL, hash or '-' for stdin

  Example usage:

      llm fragments set mydocs ./docs.md

Options:
  --help  Show this message and exit.
```

(help-fragments-show)=
#### llm fragments show --help
```
Usage: llm fragments show [OPTIONS] ALIAS_OR_HASH

  Display the fragment stored under an alias or hash

      llm fragments show mydocs

Options:
  --help  Show this message and exit.
```

(help-fragments-remove)=
#### llm fragments remove --help
```
Usage: llm fragments remove [OPTIONS] ALIAS

  Remove a fragment alias

  Example usage:

      llm fragments remove docs

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

  Store embeddings for multiple strings at once in the specified collection.

  Input data can come from one of three sources:

  1. A CSV, TSV, JSON or JSONL file:
     - CSV/TSV: First column is ID, remaining columns concatenated as content
     - JSON: Array of objects with "id" field and content fields
     - JSONL: Newline-delimited JSON objects

     Examples:
       llm embed-multi docs input.csv
       cat data.json | llm embed-multi docs -
       llm embed-multi docs input.json --format json

  2. A SQL query against a SQLite database:
     - First column returned is used as ID
     - Other columns concatenated to form content

     Examples:
       llm embed-multi docs --sql "SELECT id, title, body FROM posts"
       llm embed-multi docs --attach blog blog.db --sql "SELECT id, content FROM blog.posts"

  3. Files in directories matching glob patterns:
     - Each file becomes one embedding
     - Relative file paths become IDs

     Examples:
       llm embed-multi docs --files docs '**/*.md'
       llm embed-multi images --files photos '*.jpg' --binary
       llm embed-multi texts --files texts '*.txt' --encoding utf-8 --encoding latin-1

Options:
  --format [json|csv|tsv|nl]   Format of input file - defaults to auto-detect
  --files <DIRECTORY TEXT>...  Embed files in this directory - specify directory
                               and glob pattern
  --encoding TEXT              Encodings to try when reading --files
  --binary                     Treat --files as binary data
  --sql TEXT                   Read input using this SQL query
  --attach <TEXT FILE>...      Additional databases to attach - specify alias
                               and file path
  --batch-size INTEGER         Batch size to use when running embeddings
  --prefix TEXT                Prefix to add to the IDs
  -m, --model TEXT             Embedding model to use
  --prepend TEXT               Prepend this string to all content before
                               embedding
  --store                      Store the text itself in the database
  -d, --database FILE
  --help                       Show this message and exit.
```

(help-similar)=
### llm similar --help
```
Usage: llm similar [OPTIONS] COLLECTION [ID]

  Return top N similar IDs from a collection using cosine similarity.

  Example usage:

      llm similar my-collection -c "I like cats"

  Or to find content similar to a specific stored ID:

      llm similar my-collection 1234

Options:
  -i, --input PATH      File to embed for comparison
  -c, --content TEXT    Content to embed for comparison
  --binary              Treat input as binary data
  -n, --number INTEGER  Number of results to return
  -p, --plain           Output in plain text format
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
  -q, --query TEXT  Search for embedding models matching these strings
  --help            Show this message and exit.
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