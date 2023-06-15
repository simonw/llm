# Logging to SQLite

If a SQLite database file exists in `~/.llm/log.db` then the tool will log all prompts and responses to it.

You can create that file by running the `init-db` command:

    llm init-db

Now any prompts you run will be logged to that database.

To avoid logging a prompt, pass `--no-log` or `-n` to the command:

    llm 'Ten names for cheesecakes' -n

## Viewing the logs

You can view the logs using the `llm logs` command:

    llm logs

This will output the three most recent logged items as a JSON array of objects.

Add `-n 10` to see the ten most recent items:

    llm logs -n 10

Or `-n 0` to see everything that has ever been logged:

    llm logs -n 0

You can truncate the displayed prompts and responses using the `-t/--truncate` option:

    llm logs -n 5 -t

This is useful for finding a conversation that you would like to continue.

You can also use [Datasette](https://datasette.io/) to browse your logs like this:

    datasette ~/.llm/log.db
