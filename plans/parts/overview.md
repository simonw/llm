# The LLM "parts" project

This project represents a significant redesign and refactor of how LLM works.

There are several problems to solve here:

1. `model.prompt(parts=[list of parts])` - a way of prompting a model with more than just a single prompt, similar to how the classic OpenAI chat completions API accepts a full list of previous user/assistant messages. These parts need to cover tool usage as well. Currently LLM uses a conversation mechanism for this, most of that logic will bove into the parts=[] mechanism while the existing conversation class stays as syntactic sugar over that.
2. The database schema needs to evolve to better store more complex interactions, especially across a variety of different models. I think this means a new `llm_parts` table which may end up storing tool calls and results in addition to prompts and responses.
3. Some API models such as Claude now have mechanisms where they can execute tool calls on the server as part of a single request/response API transaction. We need to be able to store these ourselves even though we did not execute the tool calls as part of the LLM tool calling framework.
4. LLM does not have special handling for "reasoning" text yet, despite many models offering that and streaming back reasoning tokens as a separate kind of thing from text responses. Part of the rationale for the new "parts" model is that reasoning tokens are a new kind of part.
5. We need to detach the current LLM database storage from the ability to store and then re-inflate a conversation, since some users of the Python library won't be working with SQLite.

A starting point for this project is research - we need to gather detailed examples of different API models with all of their key fetures, covering Gemini and Anthropic and OpenAI and Mistral.
