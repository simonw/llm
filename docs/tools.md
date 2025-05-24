(tools)=

# Tools

Many Large Language Models have been trained to execute tools as part of responding to a prompt. LLM supports tool usage with both the command-line interface and the Python API.

## How tools work

A tool is effectively a function that the model can request to be executed. Here's how that works:

1. The initial prompt to the model includes a list of available tools, containing their names, descriptions and parameters.
2. The model can choose to call one (or sometimes more than one) of those tools, returning a request for the tool to execute.
3. The code that calls the model - in this case LLM itself - then executes the specified tool with the provided arguments.
4. LLM prompts the model a second time, this time including the output of the tool execution.
5. The model can then use that output to generate its next response.

## LLM's implementation of tools

In LLM every tool is a defined as a Python function. The function can take any number of arguments and can return a string or an object that can be converted to a string.

Tool functions should include a docstring that describes what the function does. This docstring will become the description that is passed to the model.

The Python API can accept functions directly. The command-line interface has two ways for tools to be defined: via plugins that implement the {ref}`register_tools() plugin hook <plugin-hooks-register-tools>`, or directly on the command-line using the `--functions` argument to specify a block of Python code defining one or more functions - or a path to a Python file containing the same.

You can use tools {ref}`with the LLM command-line tool <usage-tools>` or {ref}`with the Python API <python-api-tools>`.