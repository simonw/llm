(plugin-directory)=
# Plugin directory

The following plugins are available for LLM. Here's {ref}`how to install them <installing-plugins>`.

## Local models

These plugins all help you run LLMs directly on your own computer:

- **[llm-llama-cpp](https://github.com/simonw/llm-llama-cpp)** uses [llama.cpp](https://github.com/ggerganov/llama.cpp) to run models published in the GGUF format.
- **[llm-mlc](https://github.com/simonw/llm-mlc)** can run local models released by the [MLC project](https://mlc.ai/mlc-llm/), including models that can take advantage of the GPU on Apple Silicon M1/M2 devices.
- **[llm-gpt4all](https://github.com/simonw/llm-gpt4all)** adds support for various models released by the [GPT4All](https://gpt4all.io/) project that are optimized to run locally on your own machine. These models include versions of Vicuna, Orca, Falcon and MPT - here's [a full list of models](https://observablehq.com/@simonw/gpt4all-models).
- **[llm-mpt30b](https://github.com/simonw/llm-mpt30b)** adds support for the [MPT-30B](https://huggingface.co/mosaicml/mpt-30b) local model.

## Remote APIs

These plugins can be used to interact with remotely hosted models via their API:

- **[llm-mistral](https://github.com/simonw/llm-mistral)** adds support for [Mistral AI](https://mistral.ai/)'s language and embedding models.
- **[llm-gemini](https://github.com/simonw/llm-gemini)** adds support for Google's [Gemina]([https://developers.generativeai.google/](https://ai.google.dev/docs)) models.
- **[llm-claude](https://github.com/tomviner/llm-claude)** by Tom Viner adds support for Claude and Claude Instant by Anthropic.
- **[llm-anyscale-endpoints](https://github.com/simonw/llm-anyscale-endpoints)** supports models hosted on the [Anyscale Endpoints](https://app.endpoints.anyscale.com/) platform, including Llama 2 70B.
- **[llm-replicate](https://github.com/simonw/llm-replicate)** adds support for remote models hosted on [Replicate](https://replicate.com/), including Llama 2 from Meta AI.
- **[llm-palm](https://github.com/simonw/llm-palm)** adds support for Google's [PaLM 2 model](https://developers.generativeai.google/).
- **[llm-openrouter](https://github.com/simonw/llm-openrouter)** provides access to models hosted on [OpenRouter](https://openrouter.ai/).
- **[llm-cohere](https://github.com/Accudio/llm-cohere)** by Alistair Shepherd provides `cohere-generate` and `cohere-summarize` API models, powered by [Cohere](https://cohere.com/).
- **[llm-bedrock-anthropic](https://github.com/sblakey/llm-bedrock-anthropic)** adds support for Claude and Claude Instant by Anthropic via Amazon Bedrock.

If an API model host provides an OpenAI-compatible API you can also [configure LLM to talk to it](https://llm.datasette.io/en/stable/other-models.html#openai-compatible-models) without needing an extra plugin.

## Embedding models

{ref}`Embedding models <embeddings>` are models that can be used to generate and store embedding vectors for text.

- **[llm-sentence-transformers](https://github.com/simonw/llm-sentence-transformers)** adds support for embeddings using the [sentence-transformers](https://www.sbert.net/) library, which provides access to [a wide range](https://www.sbert.net/docs/pretrained_models.html) of embedding models.
- **[llm-clip](https://github.com/simonw/llm-clip)** provides the [CLIP](https://openai.com/research/clip) model, which can be used to embed images and text in the same vector space, enabling text search against images. See [Build an image search engine with llm-clip](https://simonwillison.net/2023/Sep/12/llm-clip-and-chat/) for more on this plugin.
- **[llm-embed-jina](https://github.com/simonw/llm-embed-jina)** provides Jina AI's [8K text embedding models](https://jina.ai/news/jina-ai-launches-worlds-first-open-source-8k-text-embedding-rivaling-openai/).

## Extra commands

- **[llm-python](https://github.com/simonw/llm-python)** adds a `llm python` command for running a Python interpreter in the same virtual environment as LLM. This is useful for debugging, and also provides a convenient way to interact with the LLM {ref}`python-api` if you installed LLM using Homebrew or `pipx`.
- **[llm-cluster](https://github.com/simonw/llm-cluster)** adds a `llm cluster` command for calculating clusters for a collection of embeddings. Calculated clusters can then be passed to a Large Language Model to generate a summary description.

## Just for fun

- **[llm-markov](https://github.com/simonw/llm-markov)** adds a simple model that generates output using a [Markov chain](https://en.wikipedia.org/wiki/Markov_chain). This example is used in the tutorial [Writing a plugin to support a new model](https://llm.datasette.io/en/latest/plugins/tutorial-model-plugin.html).
