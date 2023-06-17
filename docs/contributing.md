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

## Documentation

Documentation for this project uses [MyST](https://myst-parser.readthedocs.io/) - it is written in Markdown and rendered using Sphinx.

To build the documentation locally, run the following:

    cd docs
    pip install -r requirements.txt
    make livehtml

This will start a live preview server, using [sphinx-autobuild](https://pypi.org/project/sphinx-autobuild/).

The CLI `--help` examples in the documentation are managed using [Cog](https://github.com/nedbat/cog). Update those files like this:

    cog -r docs/*.md

## Release process

To release a new version:

1. Update `docs/changelog.md` with the new changes.
2. Update the version number in `setup.py`
3. [Create a GitHub release](https://github.com/simonw/llm/releases/new) for the new version.
4. Wait for the package to push to PyPI and then...
5. Run the [regenerate.yaml](https://github.com/simonw/homebrew-llm/blob/main/.github/workflows/regenerate.yaml) workflow to update the Homebrew tap to the latest version.
