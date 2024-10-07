(plugins)=
# Plugins

LLM plugins can enhance LLM by making alternative Large Language Models available, either via API or by running the models locally on your machine.

Plugins can also add new commands to the `llm` CLI tool.

Plugins can also add new Python functions that some LLM models can invoke - LLM tool calling.

The {ref}`plugin directory <plugin-directory>` lists available plugins that you can install and use.

{ref}`tutorial-model-plugin` describes how to build a new plugin in detail.

```{toctree}
---
maxdepth: 3
---
installing-plugins
directory
plugin-hooks
tutorial-model-plugin
tool-calling
plugin-utilities
```
