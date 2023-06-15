# Logging to SQLite

`llm` can log all prompts and responses to a SQLite database.

First, create a database in the correct location. You can do that using the `llm init-db` command:

```bash
llm init-db
```
This creates a database in a directory on your computer. You can find the location of that database using the `llm logs path` command:

```bash
llm logs path
```
On my Mac that outputs:
```
/Users/simon/Library/Application Support/io.datasette.llm/log.db
```
This will differ for other operating systems.

(You can customize the location of this file by setting a path in the `LLM_LOG_PATH` environment variable.)

Once that SQLite database has been created any prompts you run will be logged to that database.

To avoid logging a prompt, pass `--no-log` or `-n` to the command:
```bash
llm 'Ten names for cheesecakes' -n
```
## Viewing the logs

You can view the logs using the `llm logs` command:
```bash
llm logs
```
This will output the three most recent logged items as a JSON array of objects.

Add `-n 10` to see the ten most recent items:
```bash
llm logs -n 10
```
Or `-n 0` to see everything that has ever been logged:
```bash
llm logs -n 0
```
You can truncate the display of the prompts and responses using the `-t/--truncate` option:
```bash
llm logs -n 5 -t
```
This is useful for finding a conversation that you would like to continue.

You can also use [Datasette](https://datasette.io/) to browse your logs like this:

```bash
datasette "$(llm logs path)"
```
