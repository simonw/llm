(embeddings-writing-plugins)=
# Writing plugins to add new embedding models

Read the {ref}`plugin tutorial <tutorial-model-plugin>` for details on how to develop and package a plugin.

This page shows an example plugin that implements and registers a new embedding model.

There are two components to an embedding model plugin:

1. An implementation of the `register_embedding_models()` hook, which takes a `register` callback function and calls it to register the new model with the LLM plugin system.
2. A class that extends the `llm.EmbeddingModel` abstract base class.

    The only required method on this class is `embed_batch(texts)`, which takes an iterable of strings and returns an iterator over lists of floating point numbers.

The following example uses the [sentence-transformers](https://github.com/UKPLab/sentence-transformers) package to provide access to the [MiniLM-L6](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) embedding model.

```python
import llm
from sentence_transformers import SentenceTransformer


@llm.hookimpl
def register_embedding_models(register):
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    register(SentenceTransformerModel(model_id, model_id, 384), aliases=("all-MiniLM-L6-v2",))


class SentenceTransformerModel(llm.EmbeddingModel):
    def __init__(self, model_id, model_name, embedding_size):
        self.model_id = model_id
        self.model_name = model_name
        self.embedding_size = embedding_size
        self._model = None

    def embed_batch(self, texts):
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        results = self._model.encode(texts)
        return [list(map(float, result)) for result in results]
```
Once installed, the model provided by this plugin can be used with the {ref}`llm embed <embeddings-llm-embed>` command like this:

```bash
cat file.txt | llm embed -m sentence-transformers/all-MiniLM-L6-v2
```
Or via its registered alias like this:
```bash
cat file.txt | llm embed -m all-MiniLM-L6-v2
```
