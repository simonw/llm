# Contributing

To contribute to this tool, first checkout the code. Then create a new virtual environment:

    cd llm
    python -m venv venv
    source venv/bin/activate

Or if you are using `pipenv`:

    pipenv shell

Now install the dependencies and test dependencies:

    pip install -e '.[test]'

To run the tests:

    pytest

## Debugging tricks

The default OpenAI plugin has a debugging mechanism for showing the exact responses that came back from the OpenAI API.

Set the `LLM_OPENAI_SHOW_RESPONSES` environment variable like this:
```bash
LLM_OPENAI_SHOW_RESPONSES=1 llm -m chatgpt 'three word slogan for an an otter-run bakery'
```
This will output the response (including streaming responses) to standard error, as shown in [issues 286](https://github.com/simonw/llm/issues/286).

## Documentation

Documentation for this project uses [MyST](https://myst-parser.readthedocs.io/) - it is written in Markdown and rendered using Sphinx.

To build the documentation locally, run the following:

    cd docs
    pip install -r requirements.txt
    make livehtml

This will start a live preview server, using [sphinx-autobuild](https://pypi.org/project/sphinx-autobuild/).

The CLI `--help` examples in the documentation are managed using [Cog](https://github.com/nedbat/cog). Update those files like this:

    just cog

You'll need [Just](https://github.com/casey/just) installed to run this command.

## Release process

To release a new version:

1. Update `docs/changelog.md` with the new changes.
2. Update the version number in `setup.py`
3. [Create a GitHub release](https://github.com/simonw/llm/releases/new) for the new version.
4. Wait for the package to push to PyPI and then...
5. Run the [regenerate.yaml](https://github.com/simonw/homebrew-llm/actions/workflows/regenerate.yaml) workflow to update the Homebrew tap to the latest version.
