(tools)=

# Tools

Many Large Language Models have been trained to execute tools as part of responding to a prompt. LLM supports tool usage with both the command-line interface and the Python API.

Exposing tools to LLMs **carries risks**! Be sure to read the {ref}`warning below <tools-warning>`.

(tools-how-they-work)=

## How tools work

A tool is effectively a function that the model can request to be executed. Here's how that works:

1. The initial prompt to the model includes a list of available tools, containing their names, descriptions and parameters.
2. The model can choose to call one (or sometimes more than one) of those tools, returning a request for the tool to execute.
3. The code that calls the model - in this case LLM itself - then executes the specified tool with the provided arguments.
4. LLM prompts the model a second time, this time including the output of the tool execution.
5. The model can then use that output to generate its next response.

This sequence can run several times in a loop, allowing the LLM to access data, act on that data and then pass that data off to other tools for further processing.

:::{admonition} Tools can be dangerous
:class: danger

(tools-warning)=

## Warning: Tools can be dangerous

Applications built on top of LLMs suffer from a class of attacks called [prompt injection](https://simonwillison.net/tags/prompt-injection/) attacks. These occur when a malicious third party injects content into the LLM which causes it to take tool-based actions that act against the interests of the user of that application.

Be very careful about which tools you enable when you potentially might be exposed to untrusted sources of content - web pages, GitHub issues posted by other people, email and messages that have been sent to you that could come from an attacker.

Watch out for [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) of prompt injection exfiltration attacks. If your tool-enabled LLM has the following:

- access to private data
- exposure to malicious instructions
- the ability to exfiltrate information

Anyone who can feed malicious instructions into your LLM - by leaving them on a web page it visits, or sending an email to an inbox that it monitors - could be able to trick your LLM into using other tools to access your private information and then exfiltrate (pass out) that data to somewhere the attacker can see it.
:::

(tools-trying-out)=

## Trying out tools

LLM comes with a default tool installed, called `llm_version`. You can try that out like this:

```bash
llm --tool llm_version "What version of LLM is this?" --td
```
You can also use `-T llm_version` as a shortcut for `--tool llm_version`.

The output should look like this:
```
Tool call: llm_version({})
  0.26a0

The installed version of the LLM is 0.26a0.
```
Further tools can be installed using plugins, or you can use the `llm --functions` option to pass tools implemented as PYthon functions directly, as {ref}`described here <usage-tools>`.

(tools-implementation)=

## LLM's implementation of tools

In LLM every tool is a defined as a Python function. The function can take any number of arguments and can return a string or an object that can be converted to a string.

Tool functions should include a docstring that describes what the function does. This docstring will become the description that is passed to the model.

Tools can also be defined as {ref}`toolbox classes <python-api-toolbox>`, a subclass of `llm.Toolbox` that allows multiple related tools to be bundled together. Toolbox classes can be be configured when they are instantiated, and can also maintain state in between multiple tool calls.

The Python API can accept functions directly. The command-line interface has two ways for tools to be defined: via plugins that implement the {ref}`register_tools() plugin hook <plugin-hooks-register-tools>`, or directly on the command-line using the `--functions` argument to specify a block of Python code defining one or more functions - or a path to a Python file containing the same.

You can use tools {ref}`with the LLM command-line tool <usage-tools>` or {ref}`with the Python API <python-api-tools>`.

(tools-default)=

## Default tools

LLM includes some default tools for you to try out:

- `llm_version()` returns the current version of LLM
- `llm_time()` returns the current local and UTC time

Try them like this:

```bash
llm -T llm_version -T llm_time 'Give me the current time and LLM version' --td
```

(tools-tips)=

## Tips for implementing tools

Consult the {ref}`register_tools() plugin hook <plugin-hooks-register-tools>` documentation for examples of how to implement tools in plugins.

If your plugin needs access to API secrets I recommend storing those using `llm keys set api-name` and then reading them using the {ref}`plugin-utilities-get-key` utility function. This avoids secrets being logged to the database as part of tool calls.

<!-- Uncomment when this is true: The [llm-tools-datasette](https://github.com/simonw/llm-tools-datasette) plugin is a good example of this pattern in action. -->
