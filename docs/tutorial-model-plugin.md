# Writing a plugin to support a new model

This tutorial will walk you through developing a new plugin for LLM that adds support for a new Large Language Model.

We will be developing a plugin that implements a simple [Markov chain](https://en.wikipedia.org/wiki/Markov_chain) to generate words based on an input string. Markov chains are not technically large language models, but they provide a useful exercise for demonstrating how the LLM tool can be extended through plugins.

## The initial structure of the plugin

<!-- [ You can use the llm-simple-plugin cookiecutter template to skip this step - follow instructions in the README.

If you're not using cookiecutter, ]  -->

First create a new directory with the name of your plugin - it should be called something like `llm-markov`.
```bash
mkdir llm-markov
cd llm-markov
```
In that directory create a file called `llm_markov.py` containing this:

```python
import llm

@llm.hookimpl
def register_models(register):
    register(Markov())

class Markov(llm.Model):
    model_id = "markov"

    class Response(llm.Response):
        def iter_prompt(self, prompt):
            return ["hello world"]
```

The `def register_models()` function here is called by the plugin system (thanks to the `@hookimpl` decorator). It uses the `register()` function passed to it to register an instance of the new model.

The `Markov` class implements the model. It sets a `model_id` - an identifier that can be passed to `ll -m` in order to identify the model to be executed.

That inner class, `Markov.Response`, implements the logic of the model inside the `iter_prompt()` method. We'll extend this to do something more useful in a later step.

Next, create a `pyproject.toml` file. This is necessary to tell LLM how to load your plugin:

```toml
[project]
name = "llm-markov"
version = "0.1"

[project.entry-points.llm]
markov = "llm_markov"
```

This is the simplest possible configuration. It defines a plugin name and provides an [entry point](https://setuptools.pypa.io/en/latest/userguide/entry_point.html) for `llm` telling it how to load the plugin.

If you are comfortable with Python virtual environments you can create one now for your project, activate it and run `pip install llm` before the next step.

If you aren't familiar with virtual environments, don't worry: you can develop plugins without them. You'll need to have LLM installed using Homebrew or `pipx` or one of the [other installation options](https://llm.datasette.io/en/latest/setup.html#installation).

## Installing your plugin to try it out

Having created a directory with a `pyproject.toml` file and an `llm_markov.py` file, you can install your plugin into LLM by running this from inside your `llm-markov` directory:

```bash
llm install -e .
```

The `-e` stands for "editable" - it means you'll be able to make further changes to the `llm_markov.py` file that will be reflected without you having to reinstall the plugin.

The `.` means the current directory. You can also install editable plugins by passing a path to their directory this:
```bash
llm install -e path/to/llm-markov
```
To confirm that your plugin has installed correctly, run this command:
```bash
llm plugins
```
The output should look like this:
```json
[
  {
    "name": "llm-markov",
    "hooks": [
      "register_models"
    ],
    "version": "0.1"
  },
  {
    "name": "llm.default_plugins.openai_models",
    "hooks": [
      "register_commands",
      "register_models"
    ]
  }
]
```
This command lists default plugins that are included with LLM as well as new plugins that have been installed.

Now let's try the plugin by running a prompt through it:
```bash
llm -m markov "the cat sat on the mat"
```
It outputs:
```
hello world
```
Next, we'll make it execute and return the results of a Markov chain.

## Building the Markov chain

Markov chains can be thought of as the simplest possible example of a generative language model. They work by building an index of words that have been seen following other words.

Here's what that index looks like for the phrase "the cat sat on the mat"
```json
{
  "the": ["cat", "mat"],
  "cat": ["sat"],
  "sat": ["on"],
  "on": ["the"]
}
```
Here's a Python function that builds that data structure from a text input:
```python
def build_markov_table(text):
    words = text.split()
    transitions = {}
    # Loop through all but the last word
    for i in range(len(words) - 1):
        word = words[i]
        next_word = words[i + 1]
        transitions.setdefault(word, []).append(next_word)
    return transitions
```
We can try that out by pasting it into the interactive Python interpreter and running this:
```pycon
>>> transitions = build_markov_table("the cat sat on the mat")
>>> transitions
{'the': ['cat', 'mat'], 'cat': ['sat'], 'sat': ['on'], 'on': ['the']}
```
## Executing the Markov chain

To execute the model, we start with a word. We look at the options for words that might come next and pick one of those at random. Then we repeat that process until we have produced the desired number of output words.

Some words might not have any following words from our training sentence. For our implementation we wil fall back on picking a random word from our collection.

We will implement this as a [Python generator], using the yield keyword to produce each token:
```python
def generate(transitions, length, start_word=None):
    all_words = list(transitions.keys())
    next_word = start_word or random.choice(all_words)
    for i in range(length):
        yield next_word
        options = transitions.get(next_word) or all_words
        next_word = random.choice(options)
```
If you aren't familiar with generators, the above code could also be implemented like this - creating a Python list and returning it at the end of the function:
```python
def generate_list(transitions, length, start_word=None):
    all_words = list(transitions.keys())
    next_word = start_word or random.choice(all_words)
    output = []
    for i in range(length):
        output.append(next_word)
        options = transitions.get(next_word) or all_words
        next_word = random.choice(options)
    return output
```
You can try out the `generate()` function like this:
```python
lookup = build_markov_table("the cat sat on the mat")
for word in generate(transitions, 20):
    print(word)
```
Or you can generate a full string sentence with it like this:
```python
sentence = " ".join(generate(transitions, 20))
```
## Adding that to the plugin

Our `iter_prompt()` from earlier currently returns the list `["hello world"]`.

Update that to use our new Markov chain generator instead. Here's the full text of the new `llm_markov.py` file:

```python
import llm
import random

@llm.hookimpl
def register_models(register):
    register(Markov())

def build_markov_table(text):
    words = text.split()
    transitions = {}
    # Loop through all but the last word
    for i in range(len(words) - 1):
        word = words[i]
        next_word = words[i + 1]
        transitions.setdefault(word, []).append(next_word)
    return transitions

def generate(transitions, length, start_word=None):
    all_words = list(transitions.keys())
    next_word = start_word or random.choice(all_words)
    for i in range(length):
        yield next_word
        options = transitions.get(next_word) or all_words
        next_word = random.choice(options)

class Markov(llm.Model):
    model_id = "markov"

    class Response(llm.Response):
        def iter_prompt(self, prompt):
            text = prompt.prompt
            transitions = build_markov_table(text)
            for word in generate(transitions, 20):
                yield word + ' '
```
The `iter_prompt()` method can access the prompt that the user provided using` self.prompt.prompt` - `self.prompt` is a `Prompt` object that might include other more advanced input details as well.

Now when you run this you should see the output of the Markov chain!
```bash
llm -m markov "the cat sat on the mat"
```
```
the mat the cat sat on the cat sat on the mat cat sat on the mat cat sat on
```

## Prompts and responses are logged to the database

The prompt and the response will be logged to a SQLite database automatically by LLM. You can see the single most recent addition to the logs using:
```
llm logs -n 1
```
The output should look something like this:
```json
[
  {
    "id": 621,
    "model": "markov",
    "prompt": "the cat sat on the mat",
    "system": null,
    "prompt_json": null,
    "options_json": {},
    "response": "on the cat sat on the cat sat on the mat on the mat sat on the mat on the ",
    "response_json": null,
    "reply_to_id": null,
    "chat_id": null,
    "duration_ms": 0,
    "datetime_utc": "2023-07-06T01:31:48.074373"
  }
]
```

Plugins can log additional information to the database by assigning a dictionary to the `._response_json` property during the `iter_prompt()` method.

Here's how to include that full `transitions` table in the `response_json` in the log:
```python
    class Response(llm.Response):
        def iter_prompt(self, prompt):
            text = self.prompt.prompt
            transitions = build_markov_table(text)
            for word in generate(transitions, 20):
                yield word + ' '
            self._response_json = {"transitions": transitions}
```

Now when you run the logs command you'll see that too:
```bash
llm logs -n 1
```
```json
[
  {
    "id": 623,
    "model": "markov",
    "prompt": "the cat sat on the mat",
    "system": null,
    "prompt_json": null,
    "options_json": {},
    "response": "on the mat the cat sat on the cat sat on the mat sat on the cat sat on the ",
    "response_json": {
      "transitions": {
        "the": [
          "cat",
          "mat"
        ],
        "cat": [
          "sat"
        ],
        "sat": [
          "on"
        ],
        "on": [
          "the"
        ]
      }
    },
    "reply_to_id": null,
    "chat_id": null,
    "duration_ms": 0,
    "datetime_utc": "2023-07-06T01:34:45.376637"
  }
]
```
In this particular case this isn't a great idea here though: the `transitions` table is duplicate information, since it can be reproduced from the input data - and it can get really large for longer prompts.

## Adding options

LLM models can take options. For large language models these can be things like `temperature` or `top_k`.

Options are passed using the `-o/--option` command line parameters, for example:
```bash
llm -m gpt4 "ten pet pelican names" -o temperature 1.5
```
We're going to add two options to our Markov chain model:

- `length`: the number of words to generate
- `delay`: a floating point number of seconds to delay in between each output token

The `delay` token will let us simulate a streaming language model, where tokens take time to generate and are returned by the `iter_prompt()` function as they become ready.

Options are defined using an inner class on the model, called `Options`. It should extend the `llm.Options` class.

First, add this import to the top of your 'llm_markov.py' file:
```python
from typing import Optional
```
Then add this `Options` class to your model:
```python
class Markov(Model):
    model_id = "markov"

    class Options(llm.Options):
        length: Optional[int] = None
        delay: Optional[float] = None

```

Let's add extra validation rules to our options. Length must be at least 2. Duration must be between 0 and 10.

The `Options` class uses [Pydantic 2](https://pydantic.org/), which can support all sorts of advanced validation rules.

Add this import to the top of your 'llm_markov.py' file:
```python
from pydantic import field_validator
```

We can add a Pydantic field validator for our two new rules:

```python
    class Options(llm.Options):
        length: Optional[int] = None
        delay: Optional[float] = None

        @field_validator("length")
        def validate_length(cls, length):
            if length is None:
                return None
            if length < 2:
                raise ValueError("length must be >= 2")
            return length

        @field_validator("delay")
        def validate_delay(cls, delay):
            if delay is None:
                return None
            if not 0 <= delay <= 10:
                raise ValueError("delay must be between 0 and 10")
            return delay
```
Lets test our options validation:
```bash
llm -m markov "the cat sat on the mat" -o length -1
```
```
Error: length
  Value error, length must be >= 2
```

Next, we will modify our `iter_prompt()` method to handle those options. Add this to the beginning of `llm_markov.py`:
```python
import time
```
Then replace the `iter_prompt()` method with this one:
```python
        def iter_prompt(self, prompt):
            text = prompt.prompt
            transitions = build_markov_table(text)
            length = prompt.options.length or 10
            for word in generate(transitions, length):
                yield word + ' '
                if prompt.options.delay:
                    time.sleep(prompt.options.delay)
```
Add `can_stream = True` to the top of the `Markov` model class, on the line below `model_id = "markov". This tells LLM that the model is able to stream content to the console.

The full `llm_markov.py` file should now look like this:
```python
import llm
import random
import time
from typing import Optional
from pydantic import field_validator

@llm.hookimpl
def register_models(register):
    register(Markov())

def build_markov_table(text):
    words = text.split()
    transitions = {}
    # Loop through all but the last word
    for i in range(len(words) - 1):
        word = words[i]
        next_word = words[i + 1]
        transitions.setdefault(word, []).append(next_word)
    return transitions

def generate(transitions, length, start_word=None):
    all_words = list(transitions.keys())
    next_word = start_word or random.choice(all_words)
    for i in range(length):
        yield next_word
        options = transitions.get(next_word) or all_words
        next_word = random.choice(options)

class Markov(llm.Model):
    model_id = "markov"
    can_stream = True

    class Options(llm.Options):
        length: Optional[int] = None
        delay: Optional[float] = None

        @field_validator("length")
        def validate_length(cls, length):
            if length is None:
                return None
            if length < 2:
                raise ValueError("length must be >= 2")
            return length

        @field_validator("delay")
        def validate_delay(cls, delay):
            if delay is None:
                return None
            if not 0 <= delay <= 10:
                raise ValueError("delay must be between 0 and 10")
            return delay

    class Response(llm.Response):
        def iter_prompt(self, prompt):
            text = prompt.prompt
            transitions = build_markov_table(text)
            length = prompt.options.length or 10
            for word in generate(transitions, length):
                yield word + ' '
                if prompt.options.delay:
                    time.sleep(prompt.options.delay)
```
Now we can request a 20 word completion with a 0.1s delay between tokens like this:
```bash
llm -m markov "the cat sat on the mat" \
  -o length 20 -o delay 0.1
```
LLM provides a `--no-stream` option users can use to turn off streaming. Using that option causes LLM to gather the response from the stream and then return it to the console in one block. You can try that like this:
```bash
llm -m markov "the cat sat on the mat" \
  -o length 20 -o delay 0.1 --no-stream
```
In this case it will still delay for 2s total while it gathers the tokens, then output them all at once.

Options are also logged to the database. You can see those here:
```bash
llm logs -n 1
```
```json
[
  {
    "id": 636,
    "model": "markov",
    "prompt": "the cat sat on the mat",
    "system": null,
    "prompt_json": null,
    "options_json": {
      "length": 20,
      "delay": 0.1
    },
    "response": "the mat on the mat on the cat sat on the mat sat on the mat cat sat on the ",
    "response_json": null,
    "reply_to_id": null,
    "chat_id": null,
    "duration_ms": 2063,
    "datetime_utc": "2023-07-07T03:02:28.232970"
  }
]
```

## Distributing your plugin

There are many different options for distributing your new plugin so other people can try it out.

You can create a downloadable wheel or `.zip` or `.tar.gz` files, or share the plugin through GitHub Gists or repositories.

You can also publish your plugin to PyPI, the Python Package Index.

### Wheels and sdist packages

The easiest option is to produce a distributable package is to use the `build` command. First, install the `build` package by running this:
```bash
python -m pip install build
```
Then run `build` in your plugin directory to create the packages:
```bash
python -m build
```
This will create two files: `dist/llm-markov-0.1.tar.gz` and `dist/llm-markov-0.1-py3-none-any.whl`.

Either of these files can be used to install the plugin:

```bash
llm install dist/llm_markov-0.1-py3-none-any.whl
```
If you host this file somewhere online other people will be able to install it using `pip install` against the URL to your package:
```bash
llm install 'https://.../llm_markov-0.1-py3-none-any.whl'
```
You can run the following command at any time to uninstall your plugin, which is useful for testing out different installation methods:
```bash
llm uninstall llm-markov -y
```

### GitHub Gists

A neat quick option for distributing a simple plugin is to host it in a GitHub Gist. These are available for free with a GitHub account, and can be public or private. Gists can contain multiple files but don't support directory structures - which is OK, because our plugin is just two files, `pyproject.toml` and `llm_markov.py`.

Here's an example Gist I created for this tutorial:

[https://gist.github.com/simonw/f3686efc447678d5eb5e98331e5f18e6](https://gist.github.com/simonw/f3686efc447678d5eb5e98331e5f18e6)

You can turn a Gist into an installable `.zip` URL by right-clicking on the "Download ZIP" button and selecting "Copy Link". Here's that link for my example Gist:

`https://gist.github.com/simonw/f3686efc447678d5eb5e98331e5f18e6/archive/fe56f88f8d7927d2bad0edb9a520525cb3acd91b.zip`

The plugin can be installed using the `llm install` command like this:
```bash
llm install 'https://gist.github.com/simonw/f3686efc447678d5eb5e98331e5f18e6/archive/fe56f88f8d7927d2bad0edb9a520525cb3acd91b.zip'
```

## GitHub repositories

The same trick works for regular GitHub repositories as well: the "Download ZIP" button can be found by clicking the green "Code" button at the top of the repository. The URL which that provide scan then be used to install the plugin that lives in that repository.

## Publishing plugins to PyPI

The [Python Package Index (PyPI)](https://pypi.org/) is the official repository for Python packages. You can upload your plugin to PyPI and reserve a name for it - once you have done that, anyone will be able to install your plugin using `llm install <name>`.

Follow [these instructions](https://packaging.python.org/en/latest/tutorials/packaging-projects/#uploading-the-distribution-archives) to publish a package to PyPI. The short version:
```bash
python -m pip install twine
python -m twine upload dist/*
```
You will need an account on PyPI, then you can enter your username and password - or create a token in the PyPI settings and use `__token__` as the username and the token as the password.

## Adding metadata

Before uploading a package to PyPI it's a good idea to add documentation and expand `pyproject.toml` with additional metadata.

Create a `README.md` file in the root of your plugin directory with instructions about how to install, configure and use your plugin.

You can then replace `pyproject.toml` with something like this:

```toml
[project]
name = "llm-markov"
version = "0.1"
description = "Plugin for LLM adding a Markov chain generating model"
readme = "README.md"
authors = [{name = "Simon Willison"}]
license = {text = "Apache-2.0"}
classifiers = [
    "License :: OSI Approved :: Apache Software License"
]
dependencies = [
    "llm"
]
requires-python = ">3.7"

[project.urls]
homepage = "https://github.com/simonw/llm-markov"
Changelog = "https://github.com/simonw/llm-markov/releases"
Issues = "https://github.com/simonw/llm-markov/issues"

[project.entry-points.llm]
markov = "llm_markov"
```
This will pull in your README to be displayed as part of your project's listing page on PyPI.

It adds `llm` as a dependency, ensuring it will be installed if someone tries to install your plugin package without it.

It adds some links to useful pages (you can drop the `project.urls` section if those links are not useful for your project).

You should drop a `LICENSE` file into the GitHub repository for your package as well. I like to use the Apache 2 license [like this](https://github.com/simonw/llm/blob/main/LICENSE).
