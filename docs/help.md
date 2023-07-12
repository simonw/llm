# CLI reference

This page lists the `--help` output for all of the `llm` commands.

<!-- [[[cog
from click.testing import CliRunner
import sys
sys._called_from_test = True
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
  prompt*    Execute a prompt
  init-db    Ensure the logs.db SQLite database exists
  install    Install packages from PyPI into the same environment as LLM
  keys       Manage stored API keys for different models
  logs       Tools for exploring logged prompts and responses
  models     Manage available models
  openai     Commands for working directly with the OpenAI API
  plugins    List installed plugins
  templates  Manage stored prompt templates
  uninstall  Uninstall Python packages from the LLM environment
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
  -c, --continue               Continue the most recent conversation.
  --cid, --conversation TEXT   Continue the conversation with the given ID.
  --key TEXT                   API key to use
  --save TEXT                  Save prompt with this template name
  --help                       Show this message and exit.
```
### llm init-db --help
```
Usage: llm init-db [OPTIONS]

  Ensure the logs.db SQLite database exists

  All subsequent prompts will be logged to this database.

Options:
  --help  Show this message and exit.
```
### llm keys --help
```
Usage: llm keys [OPTIONS] COMMAND [ARGS]...

  Manage stored API keys for different models

Options:
  --help  Show this message and exit.

Commands:
  path  Output the path to the keys.json file
  set   Save a key in the keys.json file
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
  -n, --count INTEGER  Number of entries to show - 0 for all
  -p, --path FILE      Path to log database
  -t, --truncate       Truncate long strings in output
  --help               Show this message and exit.
```
### llm models --help
```
Usage: llm models [OPTIONS] COMMAND [ARGS]...

  Manage available models

Options:
  --help  Show this message and exit.

Commands:
  default  Show or set the default model
  list     List available models
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
  edit  Edit the specified prompt template using the default $EDITOR
  list  List available prompt templates
  path  Output the path to the templates directory
  show  Show the specified prompt template
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
  -U, --upgrade             Upgrade packages to latest version
  -e, --editable DIRECTORY  Install a project in editable mode from this path
  --help                    Show this message and exit.
```
### llm uninstall --help
```
Usage: llm uninstall [OPTIONS] PACKAGES...

  Uninstall Python packages from the LLM environment

Options:
  -y, --yes  Don't ask for confirmation
  --help     Show this message and exit.
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