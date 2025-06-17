# AGENTS.md

This project uses a Python environment for development and tests.

## Setting up a development environment

1. Install the project with its test dependencies:
   ```bash
   pip install -e '.[test]'
   ```
2. Run the tests:
   ```bash
   pytest
   ```

## Building the documentation

Run the following commands if you want to build the docs locally:

```bash
cd docs
pip install -r requirements.txt
make html
```
