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

You can search the logs for a search term across your prompts and the model's responses.
```bash
llm logs -q 'cheesecake'
```
The most relevant results will be shown first.

Search covers the text you typed and the text the model produced, and nothing else. System prompts, {ref}`fragment <fragments>` contents, tool calls and their output, and reasoning traces are all excluded from the index - a query only matches words that appeared in a prompt or a response. If a prompt used fragments, the fragment text is not searchable but the question you typed alongside it is.

Ranking uses [SQLite FTS5](https://www.sqlite.org/fts5.html) relevance scores, with matches in your prompt weighted well above matches in the response - what you asked is usually a stronger signal of what a conversation was about than what came back. The full [FTS5 query syntax](https://www.sqlite.org/fts5.html#full_text_query_syntax) is available, including phrase queries:
```bash
llm logs -q '"pet pelican"'
```

To switch to sorting with most recent first, add `-l/--latest`. This can be combined with `-n` to limit the number of results shown:
```bash
llm logs -q 'cheesecake' -l -n 3
```

Search spans both generations of log tables: new conversations are matched through the `turn_search` index over the content-addressed tables, and history recorded by older versions of LLM is matched through its original `responses_fts` index, with the two result sets merged. The relevance scores come from two separate indexes, so the interleaving between very old and new results is approximate.

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

(logging-message-store)=

## The message store

The `logs.db` database contains two generations of tables. Databases created by older versions of LLM recorded everything in a `responses` table, with companion tables such as `prompt_attachments` and `tool_calls` hanging off it. Current versions write to a set of **content-addressed** tables instead: `threads`, `turns`, `messages` and `parts`. Content-addressed means that rows are identified by a hash of their content rather than an assigned id, so identical content is stored exactly once.

The legacy tables are read-only history now. The `llm logs` command merges the two generations: rows that only exist in the legacy `responses` table are combined with rows from the new tables, so history recorded by an older version stays visible after an upgrade. All new logging writes only the content-addressed tables.

(logging-message-store-vocabulary)=

### Threads, turns, messages and parts

From the top down:

- A **thread** is a conversation. It is a named pointer at the message at the head of that conversation, and its id is the conversation id displayed by `llm logs`.
- A **turn** is a single model call within a thread. It records everything specific to that call - which model answered, options, token counts, timings - and points at the messages that were its input and output.
- A **message** is one entry in a conversation, with a role of `system`, `user` or `assistant`. Each message links to its parent, forming a chain, and is identified by a hash of its content combined with that parent link.
- A **part** is a piece of content within a message: text, reasoning, a tool call, a tool result or an attachment. A message's parts are ordered by their `position`.

(logging-message-store-example)=

### A worked example

Here is a two turn conversation, logged to a fresh database and then dumped. It was generated with a small scripted model that returns canned replies - every model plugin logs through the same code path, so rows written by a real model have exactly the same shape, but the canned replies keep this example deterministic.

<!-- [[[cog
import cog
import sqlite_utils
import llm

REPLIES = {
    "Suggest a name for a pet pelican": (
        "How about Percy? Pelicans suit a dignified name."
    ),
    "Now one for a pet walrus": "Wallace. It pairs nicely with Percy.",
}

class ScriptedModel(llm.Model):
    model_id = "scripted"

    def execute(self, prompt, stream, response, conversation=None):
        yield REPLIES[prompt.prompt]

db = sqlite_utils.Database(memory=True)
conversation = ScriptedModel().conversation()
for text in REPLIES:
    response = conversation.prompt(text, stream=False)
    response.text()
    response.log_to_db(db)

# ULID identifiers and timestamps differ on every run, so they are
# replaced with placeholders. The hashes are deterministic.
aliases = {}
for i, row in enumerate(db.query("select id from turns order by id")):
    aliases[row["id"]] = "$TURN_{}_ID".format(i + 1)
thread = next(db.query("select * from threads"))
aliases[thread["id"]] = "$THREAD_ID"

lines = ["messages and their parts:"]
for row in db.query("select * from messages"):
    lines.append("")
    lines.append("{} {}".format(row["role"], row["hash"]))
    lines.append("  parent: {}".format(row["parent_hash"] or "null"))
    for part in db.query(
        "select * from parts where message_hash = ? order by position",
        [row["hash"]],
    ):
        lines.append(
            "  part {}: type={} text={!r} payload={}".format(
                part["position"],
                part["type"],
                part["text"],
                part["payload"] or "null",
            )
        )
lines.append("")
lines.append("turns:")
for row in db.query("select * from turns order by id"):
    lines.append("")
    lines.append("turn {}".format(aliases[row["id"]]))
    lines.append("  thread_id: {}".format(aliases[row["thread_id"]]))
    lines.append("  parent_message_hash: {}".format(row["parent_message_hash"]))
    lines.append("  tip_message_hash:    {}".format(row["tip_message_hash"]))
    lines.append("  model: {}".format(row["model"]))
lines.append("")
lines.append("thread:")
lines.append("")
lines.append("thread $THREAD_ID")
lines.append("  name: {}".format(thread["name"]))
lines.append("  tip_message_hash: {}".format(thread["tip_message_hash"]))
cog.out("```\n{}\n```\n".format("\n".join(lines)))
]]] -->
```
messages and their parts:

user b2:d6b0cd4e7a65ea90423c50fadb3f5704
  parent: null
  part 0: type=text text='Suggest a name for a pet pelican' payload=null

assistant b2:0f2c02ad982050b623b7e034199c8c61
  parent: b2:d6b0cd4e7a65ea90423c50fadb3f5704
  part 0: type=text text='How about Percy? Pelicans suit a dignified name.' payload=null

user b2:c785dd6c77540150c2647f406cacc76f
  parent: b2:0f2c02ad982050b623b7e034199c8c61
  part 0: type=text text='Now one for a pet walrus' payload=null

assistant b2:a30a236e0d1b717c592e826d06e3c9d2
  parent: b2:c785dd6c77540150c2647f406cacc76f
  part 0: type=text text='Wallace. It pairs nicely with Percy.' payload=null

turns:

turn $TURN_1_ID
  thread_id: $THREAD_ID
  parent_message_hash: b2:d6b0cd4e7a65ea90423c50fadb3f5704
  tip_message_hash:    b2:0f2c02ad982050b623b7e034199c8c61
  model: scripted

turn $TURN_2_ID
  thread_id: $THREAD_ID
  parent_message_hash: b2:c785dd6c77540150c2647f406cacc76f
  tip_message_hash:    b2:a30a236e0d1b717c592e826d06e3c9d2
  model: scripted

thread:

thread $THREAD_ID
  name: Suggest a name for a pet pelican
  tip_message_hash: b2:a30a236e0d1b717c592e826d06e3c9d2
```
<!-- [[[end]]] -->

Things to notice:

- The four messages form a chain: the first has a `null` parent and each subsequent message names the hash of the one before it.
- The `part N:` lines show each part's storage columns. A part whose text is pure literal keeps it in the `text` column - raw, unescaped and never parsed, so text that happens to look like JSON is safe - with a `null` payload. The `payload` column holds any remaining structure as JSON: fragment references, tool call fields, provider metadata. The part's type lives only in the `type` column.
- Each turn brackets one model call. Its `parent_message_hash` is the tip of the chain that was sent to the model - the last input message, usually that turn's user prompt - and its `tip_message_hash` is the chain tip after the model's reply was appended. The prompt and response that `llm logs` displays are derived by splitting the chain at the parent, rather than being stored a second time.
- The thread's id is the conversation id, its name is derived from the first prompt and its `tip_message_hash` follows the head of the conversation as new turns are logged.
- The ULID identifiers - sortable random identifiers issued in time order, the same id space older versions used for response ids - and the timestamp columns have been replaced with placeholders because they change on every run. The hashes have not: they depend only on the message content and its position in the chain, so replaying this conversation produces these exact four hashes.

(logging-message-store-hashes)=

### Content addressing as a contract

A message's hash is calculated like this:

1. Build the object `{"parent": parent_hash, "message": message}`, where `parent_hash` is the hash of the previous message in the chain (or `null` for the first message) and `message` is the message's dictionary representation - its role, its parts and any provider metadata.
2. Serialize that object to canonical JSON: keys sorted, compact `,` and `:` separators with no extra whitespace, non-ASCII characters left unescaped.
3. Hash the UTF-8 encoding of that string with [BLAKE2b](https://en.wikipedia.org/wiki/BLAKE_(hash_function)) using a 16 byte digest, and prefix the hex digest with `b2:`.

The `b2:` prefix tags the hash with the algorithm that produced it. If a future version of LLM ever changes the digest or the canonical form, the change will be detectable instead of silently splitting the stored data into two incompatible halves.

Two design decisions matter here:

- **The hash covers resolved content.** {ref}`Fragment <usage-fragments>` references and attachment references are expanded before hashing, so the hash always covers exactly the content the model saw, never the compressed form it happens to be stored in. The internal `LogStore.verify()` method re-derives every hash from the stored rows to check this stays true.
- **The parent hash participates in the hash.** The same content appearing at a different point in a conversation is a different node. This is what makes two conversations that share a prefix collapse to shared rows, with no explicit comparison required: replaying the same messages produces the same hashes, and a hash that is already present needs nothing written.

A consequence of the second decision is that a stateless client - one that holds its own conversation history and re-sends the whole thing with every call - writes only the new tail on each request. It also makes forks cheap, as described next. Here the first conversation from the worked example is logged again, followed by a second conversation that starts with the same prompt and then diverges:

<!-- [[[cog
import cog
import sqlite_utils
import llm

REPLIES = {
    "Suggest a name for a pet pelican": (
        "How about Percy? Pelicans suit a dignified name."
    ),
    "Now one for a pet walrus": "Wallace. It pairs nicely with Percy.",
    "Now one for a pet seagull": "Steven. Steven Seagull.",
}

class ScriptedModel(llm.Model):
    model_id = "scripted"

    def execute(self, prompt, stream, response, conversation=None):
        yield REPLIES[prompt.prompt]

db = sqlite_utils.Database(memory=True)
model = ScriptedModel()

def run(prompts):
    conversation = model.conversation()
    for text in prompts:
        response = conversation.prompt(text, stream=False)
        response.text()
        response.log_to_db(db)

run(("Suggest a name for a pet pelican", "Now one for a pet walrus"))
first = {row["hash"] for row in db.query("select hash from messages")}
run(("Suggest a name for a pet pelican", "Now one for a pet seagull"))
rows = list(db.query("select * from messages"))
lines = [
    "message rows after the first conversation: {}".format(len(first)),
    "message rows after both conversations:     {}".format(len(rows)),
    "",
    "rows added by the second conversation:",
]
for row in rows:
    if row["hash"] not in first:
        lines.append("")
        lines.append("{} {}".format(row["role"], row["hash"]))
        lines.append("  parent: {}".format(row["parent_hash"]))
cog.out("```\n{}\n```\n".format("\n".join(lines)))
]]] -->
```
message rows after the first conversation: 4
message rows after both conversations:     6

rows added by the second conversation:

user b2:371ceec468c0ec797ac7042970992c0b
  parent: b2:0f2c02ad982050b623b7e034199c8c61

assistant b2:4ad19ddf94ea086aa9a8aa6fd8b0af05
  parent: b2:371ceec468c0ec797ac7042970992c0b
```
<!-- [[[end]]] -->

Two conversations of two turns each - eight messages sent to the model in total - produced six rows. The second conversation's first turn hashed to rows that were already present, so only its second turn was written, and the new user message's parent is the assistant reply both conversations share.

(logging-message-store-forking)=

### Forking and shared history

Because messages form a parent-linked tree, a conversation can fork: a new thread can point at any existing message and continue from there, sharing its entire history with the thread it came from until the two diverge. Nothing is copied when this happens. The `threads.forked_from` column records which thread a fork came from.

Shared rows cut both ways. Deleting a conversation is not the same as deleting its rows, because another thread may reach the same messages - removing them would silently corrupt that thread's history. For this reason LLM does not currently delete message rows at all; garbage collection of unreachable messages is deliberately left as future work.

(logging-message-store-references)=

### Storage by reference

The hash of a message covers its resolved content, but storage is by reference. A text part whose content borrows from a fragment does not store a copy of that fragment. Instead of a filled `text` column its payload holds a `text_ref` list of fragment references and literal segments:

```json
{"text_ref": [{"fragment": 1}, {"literal": "\nquestion about it"}]}
```

Here fragment `1` is an id in the existing `fragments` table. Reading the part concatenates the fragment content and the literal back together, reproducing the exact text that was hashed. Ask a hundred questions about a novel and the novel is stored once.

Attachments work the same way: the binary content lives in the `attachments` table, keyed by a SHA-256 hash of the bytes, and the part payload stores that id in place of the data.

(logging-message-store-tables)=

### Table by table

The full schema for these tables appears in {ref}`the SQL schema section <logging-sql-schema>` below.

- `messages` - one row per unique message. `hash` is the content address described above, `parent_hash` links to the previous message in the chain and `role` is `system`, `user` or `assistant`. `provider_metadata` holds any provider-specific data carried by the message; it participates in the hash.
- `parts` - the content of each message, ordered by `position`. `text` holds the part's literal text when it borrows no fragments - raw and never parsed, so `select text from parts` reads as prose. `payload` holds whatever structure remains as JSON (fragment references, tool call fields, provider metadata), in the order the model produced it, or NULL when the text column carries the whole part. `type` and `tool_name` are their own columns for direct filtering; the type never appears inside the payload.
- `part_attachments` and `part_fragments` - junction tables recording which rows in `attachments` and `fragments` a part's payload references, in order.
- `threads` - one row per conversation. `id` is the conversation id, `tip_message_hash` points at the current head of the conversation and `forked_from` records the thread a fork came from.
- `turns` - one row per model call. `parent_message_hash` and `tip_message_hash` bracket the call's input and output as described above, and the remaining columns record provenance: model, options, schema, token counts and timings. Turn ids are ULIDs, in the same id space as legacy response ids, which is how the two generations of tables sort together in `llm logs`.
- `turn_tools` - which {ref}`tool <tools>` definitions were available to a turn, referencing the `tools` table.
- `turn_fragments` - which fragments a turn was given, with their `kind` (`prompt` or `system`) and order. Provenance lives here rather than on the shared message rows, and this table is what powers `llm logs -f`.
- `turn_search` - the searchable text of each turn: the literal prompt the user typed (fragment content excluded, via the `text_ref` literals described above) and the assistant's text output. An FTS5 index over this table, `turn_search_fts`, is what powers {ref}`llm logs -q <logging-search>`. Derived from the stored parts when a turn is logged; a turn with no prompt or response text, such as a pure tool call, gets no row.
- `tool_instantiations` - which configured {ref}`toolbox <python-api-toolbox>` instance served a tool call: the toolbox name, its plugin and its constructor arguments, keyed by `tool_call_id`. Message rows are shared between conversations and so cannot carry this kind of local execution provenance; this table joins to the chain from outside it, and is what lets `llm logs --json` show that a `SQLite_query` call ran against `SQLite("mydb.db")`.

(logging-message-store-queries)=

### Querying the message store

These queries can be pasted into [Datasette](https://datasette.io/) or `sqlite3` against your `logs.db`. This one renders every conversation tree as indented text, resolving `text_ref` payloads back to their full text and stepping the indentation in at each fork:

```sql
with recursive
siblings as (
  select
    hash,
    parent_hash,
    count(*) over (partition by parent_hash) as branches
  from messages
),
walk as (
  select
    messages.hash,
    0 as indent,
    printf('%08d', messages.rowid) as sort_key
  from messages
  where messages.parent_hash is null
  union all
  select
    siblings.hash,
    walk.indent + (siblings.branches > 1),
    walk.sort_key || '/' || printf('%08d', messages.rowid)
  from siblings
  join messages on messages.hash = siblings.hash
  join walk on siblings.parent_hash = walk.hash
)
select
  substr('                                        ', 1, walk.indent * 4)
    || messages.role || ': '
    || coalesce(
         parts.text,
         (
           select group_concat(
             coalesce(
               json_extract(piece.value, '$.literal'),
               (select content from fragments
                 where id = json_extract(piece.value, '$.fragment'))
             ),
             '' order by piece.key
           )
           from json_each(json_extract(parts.payload, '$.text_ref')) as piece
         ),
         parts.type
       ) as entry
from walk
join messages on messages.hash = walk.hash
left join parts on parts.message_hash = messages.hash
order by walk.sort_key, parts.position;
```

Every turn that was given a specific fragment, via the `turn_fragments` provenance table - set `:fragment_hash` to a hash from `llm fragments`:

```sql
select turns.id, turns.model, turns.datetime_utc, turn_fragments.kind
from turns
join turn_fragments on turn_fragments.turn_id = turns.id
join fragments on fragments.id = turn_fragments.fragment_id
where fragments.hash = :fragment_hash
order by turns.id;
```

The most recently active conversations, with a count of their turns:

```sql
select
  threads.id,
  threads.name,
  count(turns.id) as num_turns,
  max(turns.datetime_utc) as last_used
from threads
left join turns on turns.thread_id = threads.id
group by threads.id
order by last_used desc
limit 10;
```

(logging-message-store-python)=

### Logging from Python

The supported way to write to a log database from Python is the `log_to_db()` method on a response, which is also what plugins should call:

```python
import llm
import sqlite_utils

db = sqlite_utils.Database("logs.db")
model = llm.get_model("gpt-4o-mini")
response = model.prompt("A short pelican fact")
print(response.text())
response.log_to_db(db)
```

`log_to_db()` takes a `sqlite_utils.Database` and records the response's thread, turn, messages, parts, fragments, attachments and tools in the content-addressed tables. It applies any outstanding migrations itself, so it is safe to call against a brand new database file or one created by an older version of LLM. The underlying `LogStore` class is internal and its API may change - `log_to_db()` and the table schema documented on this page are the supported interfaces.

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
    "conversations", "schemas", "responses", "responses_fts", "attachments", "prompt_attachments",
    "fragments", "fragment_aliases", "prompt_fragments", "system_fragments", "tools",
    "tool_responses", "tool_calls", "tool_results", "tool_instances",
    "tool_results_attachments",
    "messages", "parts", "part_attachments", "part_fragments",
    "threads", "turns", "turn_tools", "turn_fragments",
):
    schema = db[table].schema
    cog.out(format(cleanup_sql(schema)))
    cog.out("\n")
cog.out("```\n")
]]] -->
```sql
CREATE TABLE "conversations" (
  "id" TEXT PRIMARY KEY,
  "name" TEXT,
  "model" TEXT
);
CREATE TABLE "schemas" (
  "id" TEXT PRIMARY KEY,
  "content" TEXT
);
CREATE TABLE "responses" (
  "id" TEXT PRIMARY KEY,
  "model" TEXT,
  "prompt" TEXT,
  "system" TEXT,
  "prompt_json" TEXT,
  "options_json" TEXT,
  "response" TEXT,
  "response_json" TEXT,
  "conversation_id" TEXT REFERENCES "conversations"("id"),
  "duration_ms" INTEGER,
  "datetime_utc" TEXT,
  "input_tokens" INTEGER,
  "output_tokens" INTEGER,
  "token_details" TEXT,
  "schema_id" TEXT REFERENCES "schemas"("id"),
  "resolved_model" TEXT,
  "reasoning" TEXT
);
CREATE VIRTUAL TABLE "responses_fts" USING FTS5 (
  "prompt",
  "response",
  content="responses"
);
CREATE TABLE "attachments" (
  "id" TEXT PRIMARY KEY,
  "type" TEXT,
  "path" TEXT,
  "url" TEXT,
  "content" BLOB
);
CREATE TABLE "prompt_attachments" (
  "response_id" TEXT REFERENCES "responses"("id"),
  "attachment_id" TEXT REFERENCES "attachments"("id"),
  "order" INTEGER,
  PRIMARY KEY ("response_id",
  "attachment_id")
);
CREATE TABLE "fragments" (
  "id" INTEGER PRIMARY KEY,
  "hash" TEXT,
  "content" TEXT,
  "datetime_utc" TEXT,
  "source" TEXT
);
CREATE TABLE "fragment_aliases" (
  "alias" TEXT PRIMARY KEY,
  "fragment_id" INTEGER REFERENCES "fragments"("id")
);
CREATE TABLE "prompt_fragments" (
  "response_id" TEXT REFERENCES "responses"("id"),
  "fragment_id" INTEGER REFERENCES "fragments"("id"),
  "order" INTEGER,
  PRIMARY KEY ("response_id",
  "fragment_id",
  "order")
);
CREATE TABLE "system_fragments" (
  "response_id" TEXT REFERENCES "responses"("id"),
  "fragment_id" INTEGER REFERENCES "fragments"("id"),
  "order" INTEGER,
  PRIMARY KEY ("response_id",
  "fragment_id",
  "order")
);
CREATE TABLE "tools" (
  "id" INTEGER PRIMARY KEY,
  "hash" TEXT,
  "name" TEXT,
  "description" TEXT,
  "input_schema" TEXT,
  "plugin" TEXT
);
CREATE TABLE "tool_responses" (
  "tool_id" INTEGER REFERENCES "tools"("id"),
  "response_id" TEXT REFERENCES "responses"("id"),
  PRIMARY KEY ("tool_id",
  "response_id")
);
CREATE TABLE "tool_calls" (
  "id" INTEGER PRIMARY KEY,
  "response_id" TEXT REFERENCES "responses"("id"),
  "tool_id" INTEGER REFERENCES "tools"("id"),
  "name" TEXT,
  "arguments" TEXT,
  "tool_call_id" TEXT
);
CREATE TABLE "tool_results" (
  "id" INTEGER PRIMARY KEY,
  "response_id" TEXT REFERENCES "responses"("id"),
  "tool_id" INTEGER REFERENCES "tools"("id"),
  "name" TEXT,
  "output" TEXT,
  "tool_call_id" TEXT,
  "instance_id" INTEGER REFERENCES "tool_instances"("id"),
  "exception" TEXT
);
CREATE TABLE "tool_instances" (
  "id" INTEGER PRIMARY KEY,
  "plugin" TEXT,
  "name" TEXT,
  "arguments" TEXT
);
CREATE TABLE "tool_results_attachments" (
  "tool_result_id" INTEGER REFERENCES "tool_results"("id"),
  "attachment_id" TEXT REFERENCES "attachments"("id"),
  "order" INTEGER,
  PRIMARY KEY ("tool_result_id",
  "attachment_id")
);
CREATE TABLE "messages" (
  "hash" TEXT PRIMARY KEY,
  "parent_hash" TEXT REFERENCES "messages"("hash"),
  "role" TEXT,
  "provider_metadata" TEXT
);
CREATE TABLE "parts" (
  "id" INTEGER PRIMARY KEY,
  "message_hash" TEXT REFERENCES "messages"("hash"),
  "position" INTEGER,
  "type" TEXT,
  "tool_name" TEXT,
  "text" TEXT,
  "payload" TEXT
);
CREATE TABLE "part_attachments" (
  "part_id" INTEGER REFERENCES "parts"("id"),
  "attachment_id" TEXT REFERENCES "attachments"("id"),
  "order" INTEGER,
  PRIMARY KEY ("part_id",
  "attachment_id")
);
CREATE TABLE "part_fragments" (
  "part_id" INTEGER REFERENCES "parts"("id"),
  "fragment_id" INTEGER REFERENCES "fragments"("id"),
  "order" INTEGER,
  PRIMARY KEY ("part_id",
  "fragment_id",
  "order")
);
CREATE TABLE "threads" (
  "id" TEXT PRIMARY KEY,
  "name" TEXT,
  "tip_message_hash" TEXT REFERENCES "messages"("hash"),
  "forked_from" TEXT REFERENCES "threads"("id"),
  "datetime_utc" TEXT
);
CREATE TABLE "turns" (
  "id" TEXT PRIMARY KEY,
  "thread_id" TEXT REFERENCES "threads"("id"),
  "parent_message_hash" TEXT REFERENCES "messages"("hash"),
  "tip_message_hash" TEXT REFERENCES "messages"("hash"),
  "model" TEXT,
  "resolved_model" TEXT,
  "options_json" TEXT,
  "schema_id" TEXT REFERENCES "schemas"("id"),
  "input_tokens" INTEGER,
  "output_tokens" INTEGER,
  "token_details" TEXT,
  "duration_ms" INTEGER,
  "datetime_utc" TEXT
);
CREATE TABLE "turn_tools" (
  "turn_id" TEXT REFERENCES "turns"("id"),
  "tool_id" INTEGER REFERENCES "tools"("id"),
  PRIMARY KEY ("turn_id",
  "tool_id")
);
CREATE TABLE "turn_fragments" (
  "turn_id" TEXT REFERENCES "turns"("id"),
  "fragment_id" INTEGER REFERENCES "fragments"("id"),
  "order" INTEGER,
  "kind" TEXT,
  PRIMARY KEY ("turn_id",
  "fragment_id",
  "kind")
);
```
<!-- [[[end]]] -->
`responses_fts` configures [SQLite full-text search](https://www.sqlite.org/fts5.html) against the `prompt` and `response` columns in the `responses` table.
