(embeddings-cli)=
# Embedding with the CLI

LLM provides command-line utilities for calculating and storing embeddings for pieces of content.

(embeddings-llm-embed)=
## llm embed

The `llm embed` command can be used to calculate embedding vectors for a string of content. These can be returned directly to the terminal, stored in a SQLite database, or both.

### Returning embeddings to the terminal

The simplest way to use this command is to pass content to it using the `-c/--content` option, like this:

```bash
llm embed -c 'This is some content'
```
The command will return a JSON array of floating point numbers directly to the terminal:

```json
[0.123, 0.456, 0.789...]
```
By default it uses the {ref}`default embedding model <embeddings-cli-embed-models-default>`.

Use the `-m/--model` option to specify a different model:

```bash
llm -m sentence-transformers/all-MiniLM-L6-v2 \
  -c 'This is some content'
```
See {ref}`embeddings-binary` for options to get back embeddings in formats other than JSON.

(embeddings-collections)=
### Storing embeddings in SQLite

Embeddings are much more useful if you store them somewhere, so you can calculate similarity scores between different embeddings later on.

LLM includes the concept of a "collection" of embeddings. A collection groups together a set of stored embeddings created using the same model, each with a unique ID within that collection.

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

The following example stores the embedding for the string "my happy hound" in a collection called `phrases` under the key `hound` and using the model `ada-002`:

```bash
llm embed phrases hound -m ada-002 -c 'my happy hound'
```
By default, the SQLite database used to store embeddings is the `embeddings.db` in the user content directory managed by LLM.

You can see the path to this directory by running `llm embed-db path`.

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
  -m ada-002 \
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

(embeddings-cli-similar)=
## llm similar

The `llm similar` command searches a collection of embeddings for the items that are most similar to a given or item ID.

To search the `quotations` collection for items that are semantically similar to `'computer science'`:

```bash
llm similar quotations -c 'computer science'
```
This embeds the provided string and returns a newline-delimited list of JSON objects like this:
```json
{"id": "philkarlton-1", "score": 0.8323904531677017, "content": null, "metadata": null}
```
You can compare against text stored in a file using `-i filename`:
```bash
llm similar quotations -i one.txt
```
Or feed text to standard input using `-i -`:
```bash
echo 'computer science' | llm similar quotations -i -
```

(embeddings-cli-embed-models)=
## llm embed-models

To list all available embedding models, including those provided by plugins, run this command:

```bash
llm embed-models
```
The output should look something like this:
```
ada-002 (aliases: ada)
sentence-transformers/all-MiniLM-L6-v2 (aliases: all-MiniLM-L6-v2)
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
llm embed-models default ada-002
```
This will set the default model to OpenAI's `ada-002` model.

Any of the supported aliases for a model can be passed to this command.

You can unset the default model using `--remove-default`:

```bash
llm embed-models default --remove-default
```
When no default model is set, the `llm embed` and `llm embed-multi` commands will require that a model is specified using `-m/--model`.

## llm embed-db collections

To list all of the collections in the embeddings database, run this command:

```bash
llm embed-db collections
```
Add `--json` for JSON output:
```bash
llm embed-db collections --json
```
Add `-d/--database` to specify a different database file:
```bash
llm embed-db collections -d my-embeddings.db
```
## llm embed-db delete-collection

To delete a collection from the database, run this:
```bash
llm embed-db delete-collection collection-name
```
Pass `-d` to specify a different database file:
```bash
llm embed-db delete-collection collection-name -d my-embeddings.db
```