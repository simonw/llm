(embeddings-cli)=
# Embedding with the CLI

LLM provides command-line utilities for calculating and storing embeddings for pieces of content.

(embeddings-cli-embed)=
## llm embed

The `llm embed` command can be used to calculate embedding vectors for a string of content. These can be returned directly to the terminal, stored in a SQLite database, or both.

### Returning embeddings to the terminal

The simplest way to use this command is to pass content to it using the `-c/--content` option, like this:

```bash
llm embed -c 'This is some content' -m 3-small
```
`-m 3-small` specifies the OpenAI `text-embedding-3-small` model. You will need to have set an OpenAI API key using `llm keys set openai` for this to work.

You can install plugins to access other models. The [llm-sentence-transformers](https://github.com/simonw/llm-sentence-transformers) plugin can be used to run models on your own laptop, such as the [MiniLM-L6](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) model:

```bash
llm install llm-sentence-transformers
llm embed -c 'This is some content' -m sentence-transformers/all-MiniLM-L6-v2
```

The `llm embed` command returns a JSON array of floating point numbers directly to the terminal:

```json
[0.123, 0.456, 0.789...]
```
You can omit the `-m/--model` option if you set a {ref}`default embedding model <embeddings-cli-embed-models-default>`.

LLM also offers a binary storage format for embeddings, described in {ref}`embeddings storage format <embeddings-storage>`.

You can output embeddings using that format as raw bytes using `--format blob`, or in hexadecimal using `--format hex`, or in Base64 using `--format base64`:

```bash
llm embed -c 'This is some content' -m 3-small --format base64
```
This outputs:
```
8NGzPFtdgTqHcZw7aUT6u+++WrwwpZo8XbSxv...
```
Some models such as [llm-clip](https://github.com/simonw/llm-clip) can run against binary data. You can pass in binary data using the `-i` and `--binary` options:

```bash
llm embed --binary -m clip -i image.jpg
```
Or from standard input like this:
```bash
cat image.jpg | llm embed --binary -m clip -i -
```

(embeddings-collections)=
### Storing embeddings in SQLite

Embeddings are much more useful if you store them somewhere, so you can calculate similarity scores between different embeddings later on.

LLM includes the concept of a **collection** of embeddings. A collection groups together a set of stored embeddings created using the same model, each with a unique ID within that collection.

Embeddings also store a hash of the content that was embedded. This hash is later used to avoid calculating duplicate embeddings for the same content.

First, we'll set a default model so we don't have to keep repeating it:
```bash
llm embed-models default 3-small
```

The `llm embed` command can store results directly in a named collection like this:

```bash
llm embed quotations philkarlton-1 -c \
  'There are only two hard things in Computer Science: cache invalidation and naming things'
```
This stores the given text in the `quotations` collection under the key `philkarlton-1`.

You can also pipe content to standard input, like this:
```bash
cat one.txt | llm embed files one
```
This will store the embedding for the contents of `one.txt` in the `files` collection under the key `one`.

A collection will be created the first time you mention it.

Collections have a fixed embedding model, which is the model that was used for the first embedding stored in that collection.

In the above example this would have been the default embedding model at the time that the command was run.

The following example stores the embedding for the string "my happy hound" in a collection called `phrases` under the key `hound` and using the model `3-small`:

```bash
llm embed phrases hound -m 3-small -c 'my happy hound'
```
By default, the SQLite database used to store embeddings is the `embeddings.db` in the user content directory managed by LLM.

You can see the path to this directory by running `llm collections path`.

You can store embeddings in a different SQLite database by passing a path to it using the `-d/--database` option to `llm embed`. If this file does not exist yet the command will create it:

```bash
llm embed phrases hound -d my-embeddings.db -c 'my happy hound'
```
This creates a database file called `my-embeddings.db` in the current directory.

(embeddings-collections-content-metadata)=
#### Storing content and metadata

By default, only the entry ID and the embedding vector are stored in the database table.

You can store a copy of the original text in the `content` column by passing the `--store` option:

```bash
llm embed phrases hound -c 'my happy hound' --store
```
You can also store a JSON object containing arbitrary metadata in the `metadata` column by passing the `--metadata` option. This example uses both `--store` and `--metadata` options:

```bash
llm embed phrases hound \
  -m 3-small \
  -c 'my happy hound' \
  --metadata '{"name": "Hound"}' \
  --store
```
Data stored in this way will be returned by calls to `llm similar`, for example:
```bash
llm similar phrases -c 'hound'
```
```
{"id": "hound", "score": 0.8484683588631485, "content": "my happy hound", "metadata": {"name": "Hound"}}
```

(embeddings-cli-embed-multi)=
## llm embed-multi

The `llm embed` command embeds a single string at a time.

`llm embed-multi` can be used to embed multiple strings at once, taking advantage of any efficiencies that the embedding model may provide when processing multiple strings.

This command can be called in one of three ways:

1. With a CSV, TSV, JSON or newline-delimited JSON file
2. With a SQLite database and a SQL query
3. With one or more paths to directories, each accompanied by a glob pattern

All three mechanisms support these options:

- `-m model_id` to specify the embedding model to use
- `-d database.db` to specify a different database file to store the embeddings in
- `--store` to store the original content in the embeddings table in addition to the embedding vector
- `--prefix` to prepend a prefix to the stored ID of each item
- `--prepend` to prepend a string to the content before embedding 
- `--batch-size SIZE` to process embeddings in batches of the specified size

The `--prepend` option is useful for embedding models that require you to prepend a special token to the content before embedding it. [nomic-embed-text-v2-moe](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe) for example requires documents to be prepended `'search_document: '` and search queries to be prepended `'search_query: '`.

(embeddings-cli-embed-multi-csv-etc)=
### Embedding data from a CSV, TSV or JSON file

You can embed data from a CSV, TSV or JSON file by passing that file to the command as the second option, after the collection name.

Your file must contain at least two columns. The first one is expected to contain the ID of the item, and any subsequent columns will be treated as containing content to be embedded.

An example CSV file might look like this:

```
id,content
one,This is the first item
two,This is the second item
```
TSV would use tabs instead of commas.

JSON files can be structured like this:

```json
[
  {"id": "one", "content": "This is the first item"},
  {"id": "two", "content": "This is the second item"}
]
```
Or as newline-delimited JSON like this:
```json
{"id": "one", "content": "This is the first item"}
{"id": "two", "content": "This is the second item"}
```
In each of these cases the file can be passed to `llm embed-multi` like this:
```bash
llm embed-multi items mydata.csv
```
The first argument is the name of the collection, the second is the filename.

You can also pipe content to standard input of the tool using `-`:

```bash
cat mydata.json | llm embed-multi items -
```
LLM will attempt to detect the format of your data automatically. If this doesn't work you can specify the format using the `--format` option. This is required if you are piping newline-delimited JSON to standard input.

```bash
cat mydata.json | llm embed-multi items - --format nl
```
Other supported `--format` options are `csv`, `tsv` and `json`.

This example embeds the data from a JSON file in a collection called `items` in database called `docs.db` using the `3-small` model and stores the original content in the `embeddings` table as well, adding a prefix of `my-items/` to each ID:

```bash
llm embed-multi items mydata.json \
  -d docs.db \
  -m 3-small \
  --prefix my-items/ \
  --store
```

(embeddings-cli-embed-multi-sqlite)=
### Embedding data from a SQLite database

You can embed data from a SQLite database using `--sql`, optionally combined with `--attach` to attach an additional database.

If you are storing embeddings in the same database as the source data, you can do this:

```bash
llm embed-multi docs \
  -d docs.db \
  --sql 'select id, title, content from documents' \
  -m 3-small
```
The `docs.db` database here contains a `documents` table, and we want to embed the `title` and `content` columns from that table and store the results back in the same database.

To load content from a database other than the one you are using to store embeddings, attach it with the `--attach` option and use `alias.table` in your SQLite query:

```bash
llm embed-multi docs \
  -d embeddings.db \
  --attach other other.db \
  --sql 'select id, title, content from other.documents' \
  -m 3-small
```

(embeddings-cli-embed-multi-directories)=
### Embedding data from files in directories

LLM can embed the content of every text file in a specified directory, using the file's path and name as the ID.

Consider a directory structure like this:
```
docs/aliases.md
docs/contributing.md
docs/embeddings/binary.md
docs/embeddings/cli.md
docs/embeddings/index.md
docs/index.md
docs/logging.md
docs/plugins/directory.md
docs/plugins/index.md
```
To embed all of those documents, you can run the following:

```bash
llm embed-multi documentation \
  -m 3-small \
  --files docs '**/*.md' \
  -d documentation.db \
  --store
```
Here `--files docs '**/*.md'` specifies that the `docs` directory should be scanned for files matching the `**/*.md` glob pattern - which will match Markdown files in any nested directory.

The result of the above command is a `embeddings` table with the following IDs:

```
aliases.md
contributing.md
embeddings/binary.md
embeddings/cli.md
embeddings/index.md
index.md
logging.md
plugins/directory.md
plugins/index.md
```
Each corresponding to embedded content for the file in question.

The `--prefix` option can be used to add a prefix to each ID:

```bash
llm embed-multi documentation \
  -m 3-small \
  --files docs '**/*.md' \
  -d documentation.db \
  --store \
  --prefix llm-docs/
```
This will result in the following IDs instead:

```
llm-docs/aliases.md
llm-docs/contributing.md
llm-docs/embeddings/binary.md
llm-docs/embeddings/cli.md
llm-docs/embeddings/index.md
llm-docs/index.md
llm-docs/logging.md
llm-docs/plugins/directory.md
llm-docs/plugins/index.md
```
Files are assumed to be `utf-8`, but LLM will fall back to `latin-1` if it encounters an encoding error. You can specify a different set of encodings using the `--encoding` option.

This example will try `utf-16` first and then `mac_roman` before falling back to `latin-1`:
```
llm embed-multi documentation \
  -m 3-small \
  --files docs '**/*.md' \
  -d documentation.db \
  --encoding utf-16 \
  --encoding mac_roman \
  --encoding latin-1
```
If a file cannot be read it will be logged to standard error but the script will keep on running.

If you are embedding binary content such as images for use with CLIP, add the `--binary` option:
```
llm embed-multi photos \
  -m clip \
  --files photos/ '*.jpeg' --binary
```

(embeddings-cli-similar)=
## llm similar

The `llm similar` command searches a collection of embeddings for the items that are most similar to a given or item ID, based on [cosine similarity](https://en.wikipedia.org/wiki/Cosine_similarity).

This currently uses a slow brute-force approach which does not scale well to large collections. See [issue 216](https://github.com/simonw/llm/issues/216) for plans to add a more scalable approach via vector indexes provided by plugins.

To search the `quotations` collection for items that are semantically similar to `'computer science'`:

```bash
llm similar quotations -c 'computer science'
```
This embeds the provided string and returns a newline-delimited list of JSON objects like this:
```json
{"id": "philkarlton-1", "score": 0.8323904531677017, "content": null, "metadata": null}
```
Use `-p/--plain` to get back results in plain text instead of JSON:
```bash
llm -similar quotations -c 'computer science' -p
```
Example output:
```
philkarlton-1 (0.8323904531677017)
```
You can compare against text stored in a file using `-i filename`:
```bash
llm similar quotations -i one.txt
```
Or feed text to standard input using `-i -`:
```bash
echo 'computer science' | llm similar quotations -i -
```
When using a model like CLIP, you can find images similar to an input image using `-i filename` with `--binary`:
```bash
llm similar photos -i image.jpg --binary
```

(embeddings-cli-embed-models)=
## llm embed-models

To list all available embedding models, including those provided by plugins, run this command:

```bash
llm embed-models
```
The output should look something like this:
```
OpenAIEmbeddingModel: text-embedding-ada-002 (aliases: ada, ada-002)
OpenAIEmbeddingModel: text-embedding-3-small (aliases: 3-small)
OpenAIEmbeddingModel: text-embedding-3-large (aliases: 3-large)
...
```
Add `-q` one or more times to search for models matching those terms:
```bash
llm embed-models -q 3-small
```

(embeddings-cli-embed-models-default)=
### llm embed-models default

This command can be used to get and set the default embedding model.

This will return the name of the current default model:
```bash
llm embed-models default
```
You can set a different default like this:
```bash
llm embed-models default 3-small
```
This will set the default model to OpenAI's `3-small` model.

Any of the supported aliases for a model can be passed to this command.

You can unset the default model using `--remove-default`:

```bash
llm embed-models default --remove-default
```
When no default model is set, the `llm embed` and `llm embed-multi` commands will require that a model is specified using `-m/--model`.

## llm collections list

To list all of the collections in the embeddings database, run this command:

```bash
llm collections list
```
Add `--json` for JSON output:
```bash
llm collections list --json
```
Add `-d/--database` to specify a different database file:
```bash
llm collections list -d my-embeddings.db
```
## llm collections delete

To delete a collection from the database, run this:
```bash
llm collections delete collection-name
```
Pass `-d` to specify a different database file:
```bash
llm collections delete collection-name -d my-embeddings.db
```
