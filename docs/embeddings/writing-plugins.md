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
    register(SentenceTransformerModel(model_id, model_id), aliases=("all-MiniLM-L6-v2",))


class SentenceTransformerModel(llm.EmbeddingModel):
    def __init__(self, model_id, model_name):
        self.model_id = model_id
        self.model_name = model_name
        self._model = None

    def embed_batch(self, texts):
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        results = self._model.encode(texts)
        return (list(map(float, result)) for result in results)
```
Once installed, the model provided by this plugin can be used with the {ref}`llm embed <embeddings-cli-embed>` command like this:

```bash
cat file.txt | llm embed -m sentence-transformers/all-MiniLM-L6-v2
```
Or via its registered alias like this:
```bash
cat file.txt | llm embed -m all-MiniLM-L6-v2
```
[llm-sentence-transformers](https://github.com/simonw/llm-sentence-transformers) is a complete example of a plugin that provides an embedding model.

[Execute Jina embeddings with a CLI using llm-embed-jina](https://simonwillison.net/2023/Oct/26/llm-embed-jina/#how-i-built-the-plugin) talks through a similar process to add support for the [Jina embeddings models](https://jina.ai/news/jina-ai-launches-worlds-first-open-source-8k-text-embedding-rivaling-openai/).

## Embedding binary content

If your model can embed binary content, use the `supports_binary` property to indicate that:

```python
class ClipEmbeddingModel(llm.EmbeddingModel):
    model_id = "clip"
    supports_binary = True
    supports_text= True
```

`supports_text` defaults to `True` and so is not necessary here. You can set it to `False` if your model only supports binary data.

If your model accepts binary, your `.embed_batch()` model may be called with a list of Python bytestrings. These may be mixed with regular strings if the model accepts both types of input.

[llm-clip](https://github.com/simonw/llm-clip) is an example of a model that can embed both binary and text content.

## LLM_RAISE_ERRORS

While working on a plugin it can be useful to request that errors are raised instead of being caught and logged, so you can access them from the Python debugger.

Set the `LLM_RAISE_ERRORS` environment variable to enable this behavior, then run `llm` like this:

```bash
LLM_RAISE_ERRORS=1 python -i -m llm ...
```
The `-i` option means Python will drop into an interactive shell if an error occurs. You can then open a debugger at the most recent error using:

```python
import pdb; pdb.pm()
```