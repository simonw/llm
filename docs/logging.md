(logging)=
# Logging to SQLite

`llm` defaults to logging all prompts and responses to a SQLite database.

You can find the location of that database using the `llm logs path` command:

```bash
llm logs path
```
On my Mac that outputs:
```
/Users/simon/Library/Application Support/io.datasette.llm/logs.db
```
This will differ for other operating systems.

To avoid logging an individual prompt, pass `--no-log` or `-n` to the command:
```bash
llm 'Ten names for cheesecakes' -n
```

To turn logging by default off:

```bash
llm logs off
```
If you've turned off logging you can still log an individual prompt and response by adding `--log`:
```bash
llm 'Five ambitious names for a pet pterodactyl' --log
```
To turn logging by default back on again:

```bash
llm logs on
```
To see the status of the logs database, run this:
```bash
llm logs status
```
Example output:
```
Logging is ON for all prompts
Found log database at /Users/simon/Library/Application Support/io.datasette.llm/logs.db
Number of conversations logged: 33
Number of responses logged:     48
Database file size:             19.96MB
```

(viewing-logs)=

## Viewing the logs

You can view the logs using the `llm logs` command:
```bash
llm logs
```
This will output the three most recent logged items in Markdown format, showing both the prompt and the response formatted using Markdown.

To get back just the most recent prompt response as plain text, add `-r/--response`:

```bash
llm logs -r
```
Use `-x/--extract` to extract and return the first fenced code block from the selected log entries:

```bash
llm logs --extract
```
Or `--xl/--extract-last` for the last fenced code block:
```bash
llm logs --extract-last
```

Add `--json` to get the log messages in JSON instead:

```bash
llm logs --json
```

Add `-n 10` to see the ten most recent items:
```bash
llm logs -n 10
```
Or `-n 0` to see everything that has ever been logged:
```bash
llm logs -n 0
```
You can truncate the display of the prompts and responses using the `-t/--truncate` option. This can help make the JSON output more readable:
```bash
llm logs -n 5 -t --json
```
Or use `--prompts` to see just the truncated prompts:
```bash
llm logs -n 2 --prompts
```
Example output:
```
- model: deepseek-reasoner
  datetime: 2025-02-02T06:39:53
  conversation: 01jk2pk05xq3d0vgk0202zrsg1
  prompt:  H01 There are five huts. H02 The Scotsman lives in the purple hut. H03 The Welshman owns the parrot. H04 Kombucha is...
- model: o3-mini
  datetime: 2025-02-02T19:03:05
  conversation: 01jk40qkxetedzpf1zd8k9bgww
  system: Formatting re-enabled. Write a detailed README with extensive usage examples.
  prompt: <documents> <document index="1"> <source>./Cargo.toml</source> <document_content> [package] name = "py-limbo" version...
```

(logs-conversation)=
### Logs for a conversation

To view the logs for the most recent {ref}`conversation <conversation>` you have had with a model, use `-c`:

```bash
llm logs -c
```
To see logs for a specific conversation based on its ID, use `--cid ID` or `--conversation ID`:

```bash
llm logs --cid 01h82n0q9crqtnzmf13gkyxawg
```

### Searching the logs

You can search the logs for a search term in the `prompt` or the `response` columns.
```bash
llm logs -q 'cheesecake'
```
The most relevant terms will be shown at the bottom of the output.

### Filtering by model

You can filter to logs just for a specific model (or model alias) using `-m/--model`:
```bash
llm logs -m chatgpt
```

### Browsing logs using Datasette

You can also use [Datasette](https://datasette.io/) to browse your logs like this:

```bash
datasette "$(llm logs path)"
```
## SQL schema

Here's the SQL schema used by the `logs.db` database:

<!-- [[[cog
import cog
from llm.migrations import migrate
import sqlite_utils
import re
db = sqlite_utils.Database(memory=True)
migrate(db)

def cleanup_sql(sql):
    first_line = sql.split('(')[0]
    inner = re.search(r'\((.*)\)', sql, re.DOTALL).group(1)
    columns = [l.strip() for l in inner.split(',')]
    return first_line + '(\n  ' + ',\n  '.join(columns) + '\n);'

cog.out("```sql\n")
for table in ("conversations", "responses", "responses_fts", "attachments", "prompt_attachments"):
    schema = db[table].schema
    cog.out(format(cleanup_sql(schema)))
    cog.out("\n")
cog.out("```\n")
]]] -->
```sql
CREATE TABLE [conversations] (
  [id] TEXT PRIMARY KEY,
  [name] TEXT,
  [model] TEXT
);
CREATE TABLE [responses] (
  [id] TEXT PRIMARY KEY,
  [model] TEXT,
  [prompt] TEXT,
  [system] TEXT,
  [prompt_json] TEXT,
  [options_json] TEXT,
  [response] TEXT,
  [response_json] TEXT,
  [conversation_id] TEXT REFERENCES [conversations]([id]),
  [duration_ms] INTEGER,
  [datetime_utc] TEXT,
  [input_tokens] INTEGER,
  [output_tokens] INTEGER,
  [token_details] TEXT
);
CREATE VIRTUAL TABLE [responses_fts] USING FTS5 (
  [prompt],
  [response],
  content=[responses]
);
CREATE TABLE [attachments] (
  [id] TEXT PRIMARY KEY,
  [type] TEXT,
  [path] TEXT,
  [url] TEXT,
  [content] BLOB
);
CREATE TABLE [prompt_attachments] (
  [response_id] TEXT REFERENCES [responses]([id]),
  [attachment_id] TEXT REFERENCES [attachments]([id]),
  [order] INTEGER,
  PRIMARY KEY ([response_id],
  [attachment_id])
);
```
<!-- [[[end]]] -->
`responses_fts` configures [SQLite full-text search](https://www.sqlite.org/fts5.html) against the `prompt` and `response` columns in the `responses` table.
