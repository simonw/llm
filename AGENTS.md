# Repository maintenance notes

This project uses a Python virtual environment for development and tests.

## Setting up a development environment

1. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Install the project with its test dependencies:
   ```bash
   pip install -e '.[test]'
   ```
3. Run the tests:
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
