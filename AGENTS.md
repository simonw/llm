# AGENTS.md

This project uses [uv](https://docs.astral.sh/uv/) for development and tests.

## Setting up a development environment

1. Create a virtual environment and install dependencies:
 ```bash
 uv venv
 source .venv/bin/activate
 uv pip install -e '.[test]'
 ```
2. Run the tests:
 ```bash
 uv run pytest
 ```

## Building the documentation

Run the following commands if you want to build the docs locally:

```bash
cd docs
uv run make html
```
