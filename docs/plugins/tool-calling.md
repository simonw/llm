(tool-calling)=
# Tool calling

A plugin can expose additional tools to any supporting model via the `register_tools` plugin hook.
A plugin that implements a new LLM model can consume installed tools if the model supports tool calling.

## Registering new tools

Tools are `llm.Tool` instances holding a Python callable and a JSON schema describing the function parameters.
The callable must have a docstring that describes what it does.
If a parameter JSON schema is not provided, `llm.Tool` will introspect the callable and attempt to generate one.
For this to work, each paramater needs a `typing.Annotation` that contains the parameter type and a text description.
The function must return a string. It can raise a descriptive exception to be returned to the LLM if the tool fails.
If it raises `llm.ModelError`, that exception will be forwarded to the user.

```python
from typing import Annotated
import llm

@llm.hookimpl
def register_tools(register):
    register(llm.Tool(best_restaurant_in))

def best_restaurant_in(
    location: Annotated[str, "The city the restaurant is located in."]
) -> str:
    """Find the best restaurant in the given location."""
    return "CitiesBestRestaurant"
```

Now when the user enables tool calling, if the model supports tool calling
(the default OpenAI chat models do), then the model can invoke the tool.
```shell-session
$ llm --enable-tools -m 4o-mini 'What is the best restaurant in Asbury Park, NJ?'
The best restaurant in Asbury Park, NJ, is called "Cities Best Restaurant."
```

You can generate a parameters JSON schema using [pydantic.ModelBase.model_json_schema()](https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_json_schema), or write one by hand and pass it in to the `llm.Tool` initializer.
Here are some examples of both:

```{literalinclude} llm-sampletools/llm_sampletools.py
:language: python
```

## Using tools in models

If your plugin is implementing a new `llm.Model` class that can support tool calling,
then you can set `supports_tool_calling = True` in your model class.

You can then use the `Model.tools` property to access tools registered by your or other plugins.
The `tools` property contains a `dict` of tool names mapped to `llm.Tool` instances.
The `Tool.schema` property contains a Python dict representing the JSON schema for that tool function.
`Tool` is callable - it should be passed a JSON string representing the callables parameters.
The Tool handles any exceptions raised other than `llm.ModelError`.

Here is a skeleton implementation for a hypothetical LLM API that supports tool calling.
```python
import llmapi  # hypothetical API

class MyToolCallingModel(llm.Model):
    model_id = "toolcaller"
    supports_tool_calling = True

    def execute(self, prompt, stream, response, conversation):
        messages = [{"role": "user", "content": prompt.prompt}]
        # Invoke our hypothetical LLM API, passing in all registered tool schemas.
        completion = llmapi.chat.completion(
            messages=messages,
            tools=[tool.schema for tool in self.tools.values()]
        )
        if completion.tool_calls:
            messages.append({"role": "assistant", "tool_calls": completion.tool_calls})
            for tool_call in completion.tool_calls:
                # Find the named tool and invoke it, adding the result to messages
                tool = self.tools.get(tool_call.function.name)
                if tool:
                    # Invoke the tool with the JSON string arguments.
                    tool_response = tool(tool_call.function.arguments)
                    messages.append({"role": "tool", "content": tool_response, "tool_call_id": tool_call.id})
            # Send the tool results back to the LLM
            completion = llmapi.chat.completion(messages=messages)
            yield completion.content
        else:
            yield completion.content
```

A number of LLM APIs support tool function calling using JSON schemas to define the tools.
For example [OpenAI](https://platform.openai.com/docs/guides/function-calling),
[Anthropic](https://docs.anthropic.com/en/docs/build-with-claude/tool-use),
[Google Gemini](https://ai.google.dev/gemini-api/docs/function-calling#function_declarations),
[Ollama](https://github.com/ollama/ollama/blob/main/docs/api.md#chat-request-with-tools).