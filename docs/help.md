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

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  prompt*    Execute a prompt against on OpenAI model
  init-db    Ensure log.db SQLite database exists
  keys       Manage API keys for different models
  logs       Tools for exploring logs
  templates  Manage prompt templates
```
### llm prompt --help
```
Usage: llm prompt [OPTIONS] [PROMPT]

  Execute a prompt against on OpenAI model

Options:
  --system TEXT               System prompt to use
  -m, --model TEXT            Model to use
  -t, --template TEXT         Template to use
  -p, --param <TEXT TEXT>...  Parameters for template
  --no-stream                 Do not stream output
  -n, --no-log                Don't log to database
  -c, --continue              Continue the most recent conversation.
  --chat INTEGER              Continue the conversation with the given chat ID.
  --key TEXT                  API key to use
  --help                      Show this message and exit.
```
### llm init-db --help
```
Usage: llm init-db [OPTIONS]

  Ensure log.db SQLite database exists

Options:
  --help  Show this message and exit.
```
### llm keys --help
```
Usage: llm keys [OPTIONS] COMMAND [ARGS]...

  Manage API keys for different models

Options:
  --help  Show this message and exit.

Commands:
  path  Output path to keys.json file
  set   Save a key in keys.json
```
#### llm keys path --help
```
Usage: llm keys path [OPTIONS]

  Output path to keys.json file

Options:
  --help  Show this message and exit.
```
#### llm keys set --help
```
Usage: llm keys set [OPTIONS] NAME

  Save a key in keys.json

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

  Tools for exploring logs

Options:
  --help  Show this message and exit.

Commands:
  list*  Show logged prompts and their responses
  path   Output path to logs.db file
```
#### llm logs path --help
```
Usage: llm logs path [OPTIONS]

  Output path to logs.db file

Options:
  --help  Show this message and exit.
```
#### llm logs list --help
```
Usage: llm logs list [OPTIONS]

  Show logged prompts and their responses

Options:
  -n, --count INTEGER  Number of entries to show - 0 for all
  -p, --path FILE      Path to log database
  -t, --truncate       Truncate long strings in output
  --help               Show this message and exit.
```
### llm templates --help
```
Usage: llm templates [OPTIONS] COMMAND [ARGS]...

  Manage prompt templates

Options:
  --help  Show this message and exit.

Commands:
  edit  Edit the specified template
  list  List available templates
  path  Output path to templates directory
  show  Show the specified template
```
#### llm templates list --help
```
Usage: llm templates list [OPTIONS]

  List available templates

Options:
  --help  Show this message and exit.
```
#### llm templates show --help
```
Usage: llm templates show [OPTIONS] NAME

  Show the specified template

Options:
  --help  Show this message and exit.
```
#### llm templates edit --help
```
Usage: llm templates edit [OPTIONS] NAME

  Edit the specified template

Options:
  --help  Show this message and exit.
```
#### llm templates path --help
```
Usage: llm templates path [OPTIONS]

  Output path to templates directory

Options:
  --help  Show this message and exit.
```
<!-- [[[end]]] -->