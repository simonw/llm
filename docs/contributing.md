# Contributing

To contribute to this tool, first checkout the code. Then create a new virtual environment:
```bash
cd llm
python -m venv venv
source venv/bin/activate
```
Or if you are using `pipenv`:
```bash
pipenv shell
```
Now install the dependencies and test dependencies:
```bash
pip install -e '.[test]'
```
To run the tests:
```bash
pytest
```

## Updating recorded HTTP API interactions and associated snapshots

This project uses [pytest-recording](https://github.com/kiwicom/pytest-recording) to record OpenAI API responses for some of the tests, and [syrupy](https://github.com/syrupy-project/syrupy) to capture snapshots of their results.

If you add a new test that calls the API you can capture the API response and snapshot like this:
```bash
PYTEST_OPENAI_API_KEY="$(llm keys get openai)" pytest --record-mode once --snapshot-update
```
Then review the new snapshots in `tests/__snapshots__/` to make sure they look correct.

## Debugging tricks

The default OpenAI plugin has a debugging mechanism for showing the exact requests and responses that were sent to the OpenAI API.

Set the `LLM_OPENAI_SHOW_RESPONSES` environment variable like this:
```bash
LLM_OPENAI_SHOW_RESPONSES=1 llm -m chatgpt 'three word slogan for an an otter-run bakery'
```
This will output details of the API requests and responses to the console.

Use `--no-stream` to see a more readable version of the body that avoids streaming the response:

```bash
LLM_OPENAI_SHOW_RESPONSES=1 llm -m chatgpt --no-stream \
  'three word slogan for an an otter-run bakery'
```

## Documentation

Documentation for this project uses [MyST](https://myst-parser.readthedocs.io/) - it is written in Markdown and rendered using Sphinx.

To build the documentation locally, run the following:
```bash
cd docs
pip install -r requirements.txt
make livehtml
```
This will start a live preview server, using [sphinx-autobuild](https://pypi.org/project/sphinx-autobuild/).

The CLI `--help` examples in the documentation are managed using [Cog](https://github.com/nedbat/cog). Update those files like this:
```bash
just cog
```
You'll need [Just](https://github.com/casey/just) installed to run this command.

## Release process

To release a new version:

1. Update `docs/changelog.md` with the new changes.
2. Update the version number in `pyproject.toml`
3. [Create a GitHub release](https://github.com/simonw/llm/releases/new) for the new version.
4. Wait for the package to push to PyPI and then...
5. Run the [regenerate.yaml](https://github.com/simonw/homebrew-llm/actions/workflows/regenerate.yaml) workflow to update the Homebrew tap to the latest version.
