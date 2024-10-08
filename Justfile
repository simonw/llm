# Run tests and linters
@default: test lint

# Install dependencies and test dependencies
@init:
  uv sync --dev

# Run pytest with supplied options
@test *options:
  uv run pytest {{options}}

# Run linters
@lint:
  echo "Linters..."
  echo "  Black"
  uv run ruff format --check .
  echo "  cog"
  uv run cog --check \
    -p "import sys, os; sys._called_from_test=True; os.environ['LLM_USER_PATH'] = '/tmp'" \
    README.md docs/*.md
  echo "  mypy"
  uv run mypy llm
  echo "  ruff"
  uv run ruff check .

# Run mypy
@mypy:
  uv run mypy llm

# Rebuild docs with cog
@cog:
  uv run cog -r -p "import sys, os; sys._called_from_test=True; os.environ['LLM_USER_PATH'] = '/tmp'" docs/**/*.md docs/*.md

# Serve live docs on localhost:8000
@docs: cog
  rm -rf docs/_build
  cd docs && uv run make livehtml

# Apply Black
@black:
  uv run ruff format .

# Run automatic fixes
@fix: cog
  uv run ruff check . --fix
  uv run ruff format .

# Push commit if tests pass
@push: test lint
  git push
