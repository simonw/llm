(pinstripes-models)=

# Pinstripes models

[Pinstripes](https://pinstripes.io) offers cheap, fast Mixture-of-Experts (MoE) inference via an OpenAI-compatible API. Support for Pinstripes is built into LLM — no extra plugin is required.

(pinstripes-models-configuration)=

## Configuration

Pinstripes models are accessed using a `PINSTRIPES_API_KEY`. Obtain one at [pinstripes.io](https://pinstripes.io).

Once you have a key, configure LLM to use it by running:

```bash
llm keys set pinstripes
```
Then paste in your API key.

Alternatively, set the `PINSTRIPES_API_KEY` environment variable.

(pinstripes-models-language)=

## Available models

The following Pinstripes models are available:

| Model ID | Alias |
| --- | --- |
| `ps/deepseek-v4-flash` | `deepseek-v4-flash` |
| `ps/qwen3.6-35b-a3b` | `qwen3.6-35b` |
| `ps/qwen3-30b-a3b` | `qwen3-30b` |
| `ps/glm-4.5-air` | `glm-4.5-air` |
| `ps/minimax-m2.7` | `minimax-m2.7` |

Run `llm models` after setting your key to see the full list.

## Running a prompt

```bash
llm keys set pinstripes
# Paste Pinstripes API key here

llm -m ps/deepseek-v4-flash 'What is 2 + 2?'
```

Or use a short alias:

```bash
llm -m deepseek-v4-flash 'What is 2 + 2?'
```
