# Utility functions for plugins

LLM provides some utility functions that may be useful to plugins.

## llm.user_dir()

LLM stores various pieces of logging and configuration data in a directory on the user's machine.

On macOS this directory is `~/Library/Application Support/io.datasette.llm`, but this will differ on other operating systems.

The `llm.user_dir()` function returns the path to this directory as a `pathlib.Path` object.

Plugins can use this to store their own data in a subdirectory of this directory.

```python
import llm
user_dir = llm.user_dir()
plugin_dir = data_path = user_dir / "my-plugin"
plugin_dir.mkdir(exist_ok=True)
data_path = plugin_dir / "plugin-data.db"
```

## llm.ModelError

If your model encounters an error that should be reported to the user you can raise this exception. For example:

```python
import llm

raise ModelError("MPT model not installed - try running 'llm mpt30b download'")
```
This will be caught by the CLI layer and displayed to the user as an error message.
