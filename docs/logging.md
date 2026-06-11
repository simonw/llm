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

(logging-view)=

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
You can truncate the display of the prompts and responses using the `-t/--truncate` option. This can help make the JSON output more readable - though the `--short` option is usually better.
```bash
llm logs -n 1 -t --json
```
Example output:
```json
[
  {
    "id": "01jm8ec74wxsdatyn5pq1fp0s5",
    "model": "anthropic/claude-3-haiku-20240307",
    "prompt": "hi",
    "system": null,
    "prompt_json": null,
    "response": "Hello! How can I assist you today?",
    "conversation_id": "01jm8ec74taftdgj2t4zra9z0j",
    "duration_ms": 560,
    "datetime_utc": "2025-02-16T22:34:30.374882+00:00",
    "input_tokens": 8,
    "output_tokens": 12,
    "token_details": null,
    "conversation_name": "hi",
    "conversation_model": "anthropic/claude-3-haiku-20240307",
    "attachments": []
  }
]
```

(logging-short)=

### -s/--short mode

Use `-s/--short` to see a shortened YAML log with truncated prompts and no responses:
```bash
llm logs -n 2 --short
```
Example output:
```yaml
- model: deepseek-reasoner
  datetime: '2025-02-02T06:39:53'
  conversation: 01jk2pk05xq3d0vgk0202zrsg1
  prompt:  H01 There are five huts. H02 The Scotsman lives in the purple hut. H03 The Welshman owns the parrot. H04 Kombucha is...
- model: o3-mini
  datetime: '2025-02-02T19:03:05'
  conversation: 01jk40qkxetedzpf1zd8k9bgww
  system: Formatting re-enabled. Write a detailed README with extensive usage examples.
  prompt: <documents> <document index="1"> <source>./Cargo.toml</source> <document_content> [package] name = "py-limbo" version...
```
Include `-u/--usage` to include token usage information:

```bash
llm logs -n 1 --short --usage
```
Example output:
```yaml
- model: o3-mini
  datetime: '2025-02-16T23:00:56'
  conversation: 01jm8fxxnef92n1663c6ays8xt
  system: Produce Python code that demonstrates every possible usage of yaml.dump
    with all of the arguments it can take, especi...
  prompt: <documents> <document index="1"> <source>./setup.py</source> <document_content>
    NAME = 'PyYAML' VERSION = '7.0.0.dev0...
  usage:
    input: 74793
    output: 3550
    details:
      completion_tokens_details:
        reasoning_tokens: 2240
```

(logging-conversation)=

### Logs for a conversation

To view the logs for the most recent {ref}`conversation <usage-conversation>` you have had with a model, use `-c`:

```bash
llm logs -c
```
To see logs for a specific conversation based on its ID, use `--cid ID` or `--conversation ID`:

```bash
llm logs --cid 01h82n0q9crqtnzmf13gkyxawg
```

(logging-search)=

### Searching the logs

You can search the logs for a search term in the `prompt` or the `response` columns.
```bash
llm logs -q 'cheesecake'
```
The most relevant results will be shown first.

To switch to sorting with most recent first, add `-l/--latest`. This can be combined with `-n` to limit the number of results shown:
```bash
llm logs -q 'cheesecake' -l -n 3
```

(logging-filter-id)=

### Filtering past a specific ID

If you want to retrieve all of the logs that were recorded since a specific response ID you can do so using these options:

- `--id-gt $ID` - every record with an ID greater than $ID
- `--id-gte $ID` - every record with an ID greater than or equal to $ID

IDs are always issued in ascending order by time, so this provides a useful way to see everything that has happened since a particular record.

This can be particularly useful when {ref}`working with schema data <schemas-logs>`, where you might want to access every record that you have created using a specific `--schema` but exclude records you have previously processed.

(logging-filter-model)=

### Filtering by model

You can filter to logs just for a specific model (or model alias) using `-m/--model`:
```bash
llm logs -m chatgpt
```

(logging-filter-fragments)=

### Filtering by prompts that used specific fragments

The `-f/--fragment X` option will filter for just responses that were created using the specified {ref}`fragment <usage-fragments>` hash or alias or URL or filename.

Fragments are displayed in the logs as their hash ID. Add `-e/--expand` to display fragments as their full content - this option works for both the default Markdown and the `--json` mode:

```bash
llm logs -f https://llm.datasette.io/robots.txt --expand
```
You can display just the content for a specific fragment hash ID (or alias) using the `llm fragments show` command:

```bash
llm fragments show 993fd38d898d2b59fd2d16c811da5bdac658faa34f0f4d411edde7c17ebb0680
```
If you provide multiple fragments you will get back responses that used _all_ of those fragments.

(logging-filter-tools)=

### Filtering by prompts that used specific tools

You can filter for responses that used tools from specific fragments with the `--tool/-T` option:

```bash
llm logs -T simple_eval
```
This will match responses that involved a _result_ from that tool. If the tool was not executed it will not be included in the filtered responses.

Pass `--tool/-T` multiple times for responses that used all of the specified tools.

Use the `llm logs --tools` flag to see _all_ responses that involved at least one tool result, including from `--functions`:

```bash
llm logs --tools
```

(logging-filter-schemas)=

### Browsing data collected using schemas

The `--schema X` option can be used to view responses that used the specified schema, using any of the {ref}`ways to specify a schema <schemas-specify>`:

```bash
llm logs --schema 'name, age int, bio'
```

This can be combined with `--data` and `--data-array` and `--data-key` to extract just the returned JSON data - consult the {ref}`schemas documentation <schemas-logs>` for details.

(logging-datasette)=

## Browsing logs using Datasette

You can also use [Datasette](https://datasette.io/) to browse your logs like this:

```bash
datasette "$(llm logs path)"
```

(logging-backup)=

## Backing up your database

You can backup your logs to another file using the `llm logs backup` command:

```bash
llm logs backup /tmp/backup.db
```
This uses SQLite [VACUUM INTO](https://sqlite.org/lang_vacuum.html#vacuum_with_an_into_clause) under the hood.

(logging-sql-schema)=

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
for table in (
    "conversations", "schemas", "responses", "responses_fts", "attachments",
    "fragments", "fragment_aliases", "tools", "tool_instances",
    "messages", "parts", "part_attachments", "nodes",
    "response_fragments", "response_tools",
):
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
CREATE TABLE [schemas] (
  [id] TEXT PRIMARY KEY,
  [content] TEXT
);
CREATE TABLE [responses] (
  [id] TEXT PRIMARY KEY,
  [model] TEXT,
  [resolved_model] TEXT,
  [conversation_id] TEXT REFERENCES [conversations]([id]),
  [input_node_id] TEXT REFERENCES [nodes]([id]),
  [first_input_node_id] TEXT REFERENCES [nodes]([id]),
  [output_node_id] TEXT REFERENCES [nodes]([id]),
  [prompt] TEXT,
  [system] TEXT,
  [response] TEXT,
  [reasoning] TEXT,
  [options_json] TEXT,
  [schema_id] TEXT REFERENCES [schemas]([id]),
  [prompt_json] TEXT,
  [response_json] TEXT,
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
CREATE TABLE [fragments] (
  [id] INTEGER PRIMARY KEY,
  [hash] TEXT,
  [content] TEXT,
  [datetime_utc] TEXT,
  [source] TEXT
);
CREATE TABLE [fragment_aliases] (
  [alias] TEXT PRIMARY KEY,
  [fragment_id] INTEGER REFERENCES [fragments]([id])
);
CREATE TABLE [tools] (
  [id] INTEGER PRIMARY KEY,
  [hash] TEXT,
  [name] TEXT,
  [description] TEXT,
  [input_schema] TEXT,
  [plugin] TEXT
);
CREATE TABLE [tool_instances] (
  [id] INTEGER PRIMARY KEY,
  [plugin] TEXT,
  [name] TEXT,
  [arguments] TEXT
);
CREATE TABLE [messages] (
  [id] TEXT PRIMARY KEY,
  [role] TEXT,
  [provider_metadata] TEXT
);
CREATE TABLE [parts] (
  [id] INTEGER PRIMARY KEY,
  [message_id] TEXT REFERENCES [messages]([id]),
  [order] INTEGER,
  [type] TEXT,
  [text] TEXT,
  [redacted] INTEGER,
  [name] TEXT,
  [arguments] TEXT,
  [output] TEXT,
  [tool_call_id] TEXT,
  [server_executed] INTEGER,
  [exception] TEXT,
  [instance_id] INTEGER REFERENCES [tool_instances]([id]),
  [attachment_id] TEXT REFERENCES [attachments]([id]),
  [provider_metadata] TEXT
);
CREATE TABLE [part_attachments] (
  [part_id] INTEGER REFERENCES [parts]([id]),
  [attachment_id] TEXT REFERENCES [attachments]([id]),
  [order] INTEGER,
  PRIMARY KEY ([part_id],
  [order])
);
CREATE TABLE [nodes] (
  [id] TEXT PRIMARY KEY,
  [parent_id] TEXT REFERENCES [nodes]([id]),
  [message_id] TEXT REFERENCES [messages]([id]),
  [depth] INTEGER
);
CREATE TABLE [response_fragments] (
  [response_id] TEXT REFERENCES [responses]([id]),
  [fragment_id] INTEGER REFERENCES [fragments]([id]),
  [fragment_type] TEXT,
  [order] INTEGER,
  PRIMARY KEY ([response_id],
  [fragment_type],
  [order])
);
CREATE TABLE [response_tools] (
  [response_id] TEXT REFERENCES [responses]([id]),
  [tool_id] INTEGER REFERENCES [tools]([id]),
  PRIMARY KEY ([response_id],
  [tool_id])
);
```
<!-- [[[end]]] -->
`responses_fts` configures [SQLite full-text search](https://www.sqlite.org/fts5.html) against the `prompt` and `response` columns in the `responses` table.

(logging-messages-nodes)=

## Messages, parts and nodes

Each row in `responses` records one model call. The full structured content of that call - text, reasoning, tool calls, tool results and attachments, in their original order with any provider metadata - lives in three further tables:

- `messages` stores each message exactly once. The `id` is a content hash of the message's canonical JSON form, so a message that appears in many conversation turns (or many conversations) is stored a single time.
- `parts` stores the typed content of each message: one row per part with columns for the part `type` (`text`, `reasoning`, `tool_call`, `tool_result` or `attachment`) and its fields.
- `nodes` gives messages a position. Each node points at its parent node and the message at that position; a conversation is the path from a root node to a leaf. Each response records the leaf of the chain it sent (`input_node_id`), where its new input began (`first_input_node_id`) and the leaf after its output (`output_node_id`). The next turn extends `output_node_id`, so a long conversation stores each message once no matter how many turns follow it.

Four SQL views make this convenient to query:

- `response_chains` - every message each response saw or produced, with a `scope` column of `history`, `input` or `output`
- `response_tool_calls` - tool calls made by each response
- `response_tool_results` - tool results each response received
- `response_attachments` - attachments included with each response's input

For example, to see all reasoning text along with any redacted-reasoning markers:

```sql
select response_id, parts.redacted, parts.text
from response_chains
join parts on parts.message_id = response_chains.message_id
where scope = 'output' and parts.type = 'reasoning'
```

## Upgrading from older versions

Databases created before the node-tree schema are converted automatically the first time a newer LLM touches them. The original tables are never modified: the old `responses` table is renamed to `responses_archive` and the old `tool_calls`, `tool_results`, `prompt_attachments`, `prompt_fragments`, `system_fragments` and `tool_responses` tables keep their names and rows as an untouched safety net. Conversion copies everything into the new tables, preserving response and conversation IDs.

If any rows fail to convert they are recorded in the `_conversion_errors` table and skipped - your other logs are unaffected. Run this command to retry them:

```bash
llm logs backfill
```
