(plugin-directory)=
# Plugin directory

The following plugins are available for LLM. Here's {ref}`how to install them <installing-plugins>`.

## Local models

These plugins all help you run LLMs directly on your own computer:

- **[llm-mlc](https://github.com/simonw/llm-mlc)** can run local models released by the [MLC project](https://mlc.ai/mlc-llm/), including models that can take advantage of the GPU on Apple Silicon M1/M2 devices.
- **[llm-llama-cpp](https://github.com/simonw/llm-llama-cpp)** uses [llama.cpp](https://github.com/ggerganov/llama.cpp) to run models published in the GGML format.
- **[llm-gpt4all](https://github.com/simonw/llm-gpt4all)** adds support for various models released by the [GPT4All](https://gpt4all.io/) project that are optimized to run locally on your own machine. These models include versions of Vicuna, Orca, Falcon and MPT - here's [a full list of models](https://observablehq.com/@simonw/gpt4all-models).
- **[llm-mpt30b](https://github.com/simonw/llm-mpt30b)** adds support for the [MPT-30B](https://huggingface.co/mosaicml/mpt-30b) local model.

## Remote APIs

These plugins can be used to interact with remotely hosted models via their API:

- **[llm-palm](https://github.com/simonw/llm-palm)** adds support for Google's [PaLM 2 model](https://developers.generativeai.google/).
- **[llm-replicate](https://github.com/simonw/llm-replicate)** adds support for remote models hosted on [Replicate](https://replicate.com/), including Llama 2 from Meta AI.
- **[llm-claude](https://github.com/tomviner/llm-claude)** by Tom Viner adds support for Claude and Claude Instant by Anthropic.
- **[llm-openrouter](https://github.com/simonw/llm-openrouter)** provides access to models hosted on [OpenRouter](https://openrouter.ai/).
- **[llm-anyscale-endpoints](https://github.com/simonw/llm-anyscale-endpoints)** supports models hosted on the [Anyscale Endpoints](https://app.endpoints.anyscale.com/) platform, including Llama 2 70B.

If an API model host provides an OpenAI-compatible API you can also [configure LLM to talk to it](https://llm.datasette.io/en/stable/other-models.html#openai-compatible-models) without needing an extra plugin.

## Just for fun

- **[llm-markov](https://github.com/simonw/llm-markov)** adds a simple model that generates output using a [Markov chain](https://en.wikipedia.org/wiki/Markov_chain). This example is used in the tutorial [Writing a plugin to support a new model](https://llm.datasette.io/en/latest/plugins/tutorial-model-plugin.html).
