(embeddings)=
# Embeddings

Embedding models allow you to take a piece of text - a word, sentence, paragraph or even a whole article, and convert that into an array of floating point numbers.

This floating point array is called an "embedding vector", and works as a numerical representation of the semantic meaning of the content in a many-multi-dimensional space.

By calculating the distance between embedding vectors, we can identify which content is semantically "nearest" to other content.

This can be used to build features like related article lookups. It can also be used to build semantic search, where a user can search for a phrase and get back results that are semantically similar to that phrase even if they do not share any exact keywords.

Some embedding models like [CLIP](https://github.com/simonw/llm-clip) can even work against binary files such as images. These can be used to search for images that are similar to other images, or to search for images that are semantically similar to a piece of text.

LLM supports multiple embedding models through {ref}`plugins <plugins>`. Once installed, an embedding model can be used on the command-line or via the Python API to calculate and store embeddings for content, and then to perform similarity searches against those embeddings.

See [LLM now provides tools for working with embeddings](https://simonwillison.net/2023/Sep/4/llm-embeddings/) for an extended explanation of embeddings, why they are useful and what you can do with them.

```{toctree}
---
maxdepth: 3
---
cli
python-api
writing-plugins
binary
```
