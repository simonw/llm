# Run tests and linters
@default: test lint

# Run pytest with supplied options
@test *options:
  pipenv run pytest {{options}}

# Run linters
@lint:
  pipenv run black . --check
  pipenv run cog --check README.md docs/*.md

# Rebuild docs with cog
@cog:
  pipenv run cog -r docs/*.md

# Serve live docs on localhost:8000
@docs: cog
  cd docs && pipenv run make livehtml

# Apply Black
@black:
  pipenv run black .
