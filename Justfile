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
  echo "Linters..."
  echo "  Black"
  pipenv run black . --check
  echo "  cog"
  pipenv run cog --check \
    -p "import sys, os; sys._called_from_test=True; os.environ['LLM_USER_PATH'] = '/tmp'" \
    README.md docs/*.md
  echo "  mypy"
  pipenv run mypy llm
  echo "  ruff"
  pipenv run ruff .

# Rebuild docs with cog
@cog:
  pipenv run cog -r -p "import sys, os; sys._called_from_test=True; os.environ['LLM_USER_PATH'] = '/tmp'" docs/**/*.md docs/*.md

# Serve live docs on localhost:8000
@docs: cog
  rm -rf docs/_build
  cd docs && pipenv run make livehtml

# Apply Black
@black:
  pipenv run black .

# Run automatic fixes
@fix: cog
  pipenv run ruff . --fix
  pipenv run black .

# Push commit if tests pass
@push: test lint
  git push
