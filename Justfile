# Run tests and linters
@default: test lint

# Install dependencies and test dependencies
@init:
  pipenv run pip install -e '.[test]'

# Run pytest with supplied options
@test *options:
  pipenv run pytest {{options}}

# Run linters
@lint:
  pipenv run black . --check
  pipenv run cog --check README.md docs/*.md
  pipenv run mypy llm
  pipenv run ruff .

# Rebuild docs with cog
@cog:
  pipenv run cog -r docs/*.md

# Serve live docs on localhost:8000
@docs: cog
  cd docs && pipenv run make livehtml

# Apply Black
@black:
  pipenv run black .

# Run automatic fixes
@fix: cog black
  pipenv run ruff . --fix
