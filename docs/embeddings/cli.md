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
llm embed -m ada-002 -c 'my happy hound' phrases hound
```
By default, the SQLite database used to store embeddings is the `embeddings.db` in the user content directory managed by LLM.

You can see the path to this directory by running `llm embed-db path`.

You can store embeddings in a different SQLite database by passing a path to it using the `-d/--database` option to `llm embed`. If this file does not exist yet the command will create it:

```bash
llm embed -d my-embeddings.db -c 'my happy hound' phrases hound
```
This creates a database file called `my-embeddings.db` in the current directory.

(embeddings-cli-embed-models-default)=
## llm embed-models default

This command can be used to get and set the default embedding model.

This will return the name of the current default model:
```bash
llm embed-models default
```
You can set a different default like this:
```
llm embed-models default name-of-other-model
```
Any of the supported aliases for a model can be passed to this command.

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
