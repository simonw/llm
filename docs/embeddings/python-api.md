(embeddings-python-api)=
# Using embeddings from Python

You can load an embedding model using its model ID or alias like this:
```python
import llm

embedding_model = llm.get_embedding_model("ada-002")
```
To embed a string, returning a Python list of floating point numbers, use the `.embed()` method:
```python
vector = embedding_model.embed("my happy hound")
```
Many embeddings models are more efficient when you embed multiple strings at once. To embed multiple strings at once, use the `.embed_multi()` method:
```python
vectors = list(embedding_model.embed_multi(["my happy hound", "my dissatisfied cat"]))
```
This returns a generator that yields one embedding vector per string.

(embeddings-python-collections)=
## Working with collections

The `llm.Collection` class can be used to work with **collections** of embeddings from Python code.

A collection is a named group of embedding vectors, each stored along with their IDs in a SQLite database table.

To work with embeddings in this way you will need an instance of a [sqlite-utils Database](https://sqlite-utils.datasette.io/en/stable/python-api.html#connecting-to-or-creating-a-database) object. You can then pass that to the `llm.Collection` constructor along with the unique string name of the collection and the ID of the embedding model you will be using with that collection:

```python
import sqlite_utils
import llm

# This collection will use an in-memory database that will be
# discarded when the Python process exits
collection = llm.Collection("entries", model_id="ada-002")

# Or you can persist the database to disk like this:
db = sqlite_utils.Database("my-embeddings.db")
collection = llm.Collection("entries", db, model_id="ada-002")

# You can pass a model directly using model= instead of model_id=
embedding_model = llm.get_embedding_model("ada-002")
collection = llm.Collection("entries", db, model=embedding_model)
```
If the collection already exists in the database you can omit the `model` or `model_id` argument - the model ID will be read from the `collections` table.

To embed a single string and store it in the collection, use the `embed()` method:

```python
collection.embed("hound", "my happy hound")
```
This stores the embedding for the string "my happy hound" in the `entries` collection under the key `hound`.

Add `store=True` to store the text content itself in the database table along with the embedding vector.

To attach additional metadata to an item, pass a JSON-compatible dictionary as the `metadata=` argument:

```python
collection.embed("hound", "my happy hound", metadata={"name": "Hound"}, store=True)
```
This additional metadata will be stored as JSON in the `metadata` column of the embeddings database table.

(embeddings-python-bulk)=
### Storing embeddings in bulk

The `collection.embed_multi()` method can be used to store embeddings for multiple strings at once. This can be more efficient for some embedding models.

```python
collection.embed_multi(
    [
        ("hound", "my happy hound"),
        ("cat", "my dissatisfied cat"),
    ],
    # Add this to store the strings in the content column:
    store=True,
)
```
To include metadata to be stored with each item, call `embed_multi_with_metadata()`:

```python
collection.embed_multi_with_metadata(
    [
        ("hound", "my happy hound", {"name": "Hound"}),
        ("cat", "my dissatisfied cat", {"name": "Cat"}),
    ],
    # This can also take the store=True argument:
    store=True,
)
```

(embeddings-python-collection-class)=
### Collection class reference

A collection instance has the following properties and methods:

- `id` - the integer ID of the collection in the database
- `name` - the string name of the collection (unique in the database)
- `model_id` - the string ID of the embedding model used for this collection
- `model()` - returns the `EmbeddingModel` instance, based on that `model_id`
- `count()` - returns the integer number of items in the collection
- `embed(id: str, text: str, metadata: dict=None, store: bool=False)` - embeds the given string and stores it in the collection under the given ID. Can optionally include metadata (stored as JSON) and store the text content itself in the database table.
- `embed_multi(entries: Iterable, store: bool=False)` - see above
- `embed_multi_with_metadata(entries: Iterable, store: bool=False)` - see above
- `similar(query: str, number: int=10)` - returns a list of entries that are most similar to the embedding of the given query string
- `similar_by_id(id: str, number: int=10)` - returns a list of entries that are most similar to the embedding of the item with the given ID
- `similar_by_vector(vector: List[float], number: int=10, skip_id: str=None)` - returns a list of entries that are most similar to the given embedding vector, optionally skipping the entry with the given ID

(embeddings-python-similar)=
## Retrieving similar items

Once you have populated a collection of embeddings you can retrieve the entries that are most similar to a given string using the `similar()` method:

```python
for entry in collection.similar("hound"):
    print(entry.id, entry.score)
```
The string will first by embedded using the model for the collection.

The `entry` object returned is an object with the following properties:

- `id` - the string ID of the item
- `score` - the floating point similarity score between the item and the query string
- `content` - the string text content of the item, if it was stored - or `None`
- `metadata` - the dictionary (from JSON) metadata for the item, if it was stored - or `None`

This defaults to returning the 10 most similar items. You can change this by passing a different `number=` argument:
```python
for id, score in collection.similar("hound", number=5):
    print(id, score)
```
The `similar_by_id()` method takes the ID of another item in the collection and returns the most similar items to that one, based on the embedding that has already been stored for it:

```python
for id, score in collection.similar_by_id("cat"):
    print(id, score)
```
The item itself is excluded from the results.

(embeddings-sql-schema)=
## SQL schema

Here's the SQL schema used by the embeddings database:

<!-- [[[cog
import cog
from llm.embeddings_migrations import embeddings_migrations
import sqlite_utils
import re
db = sqlite_utils.Database(memory=True)
embeddings_migrations.apply(db)

cog.out("```sql\n")
for table in ("collections", "embeddings"):
    schema = db[table].schema
    cog.out(format(schema))
    cog.out("\n")
cog.out("```\n")
]]] -->
```sql
CREATE TABLE [collections] (
   [id] INTEGER PRIMARY KEY,
   [name] TEXT,
   [model] TEXT
)
CREATE TABLE "embeddings" (
   [collection_id] INTEGER REFERENCES [collections]([id]),
   [id] TEXT,
   [embedding] BLOB,
   [content] TEXT,
   [content_hash] BLOB,
   [metadata] TEXT,
   [updated] INTEGER,
   PRIMARY KEY ([collection_id], [id])
)
```
<!-- [[[end]]] -->