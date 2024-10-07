(tool-calling)=
# Tool calling

A plugin can expose additional tools to any supporting model via the `register_tools` plugin hook.
A plugin that implements a new LLM model can consume installed tools if the model supports tool calling.

## Registering new tools

Tools are simply fully annotated Python functions, decorated with the `llm.Tool` decorator.
The function must have a docstring that describes what it does, and each paramater needs
an `Annotation` string that describes that parameter.
The function must return a string. It can raise a descriptive exception to be returned to the LLM if the tool fails.
If it raises `llm.ModelError`, that exception will be forwarded to the user.

```python
import random
import sys
from typing import Annotated
import llm


@llm.hookimpl
def register_tools(register):
    register(random_number)


@llm.Tool
def random_number(
    minimum: Annotated[int, "The minimum value of the random number, default is 0"] = 0,
    maximum: Annotated[
        int, f"The maximum value of the random number, default is {sys.maxsize}."
    ] = sys.maxsize,
) -> str:
    """Generate a random number."""
    return str(random.randrange(maximum))
```

Now when the user enables tool calling, if the model supports tool calling
(e.g. the default OpenAI chat models do), then the model can invoke the tool.
```shell-session
$ llm --enable-tools -m 4o-mini 'Generate a random number, maximum 1000'
The generated random number is 485.
```

## Using tools in models

If your plugin is implementing a new `llm.Model` class that can support tool calling,
then you can set `supports_tool_calling = True` in your model class.

You can then use the `Model.tools` property to access tools registered by your or other plugins.
The `tools` property contains a `dict` of tool names mapped to `llm.Tool` instances.
The `Tool.schema` property contains a Python dict representing the JSON schema for that tool function.
`Tool` is callable - you can also call `Tool.safe_call(json_args: str)` to invoke the tool with a JSON
string representing the keyword arguments - this handles any tool invocation exceptions.

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
                    tool_response = tool.safe_call(tool_call.function.arguments)
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