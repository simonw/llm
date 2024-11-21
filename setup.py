from setuptools import setup, find_packages
import os

VERSION = "0.19a2"


def get_long_description():
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md"),
        encoding="utf8",
    ) as fp:
        return fp.read()


setup(
    name="llm",
    description=(
        "A CLI utility and Python library for interacting with Large Language Models, "
        "including OpenAI, PaLM and local models installed on your own machine."
    ),
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Simon Willison",
    url="https://github.com/simonw/llm",
    project_urls={
        "Documentation": "https://llm.datasette.io/",
        "Issues": "https://github.com/simonw/llm/issues",
        "CI": "https://github.com/simonw/llm/actions",
        "Changelog": "https://github.com/simonw/llm/releases",
    },
    license="Apache License, Version 2.0",
    version=VERSION,
    packages=find_packages(),
    entry_points="""
        [console_scripts]
        llm=llm.cli:cli
    """,
    install_requires=[
        "click",
        "openai>=1.0",
        "click-default-group>=1.2.3",
        "sqlite-utils>=3.37",
        "sqlite-migrate>=0.1a2",
        "pydantic>=1.10.2",
        "PyYAML",
        "pluggy",
        "python-ulid",
        "setuptools",
        "pip",
        "pyreadline3; sys_platform == 'win32'",
        "puremagic",
    ],
    extras_require={
        "test": [
            "pytest",
            "numpy",
            "pytest-httpx>=0.33.0",
            "pytest-asyncio",
            "cogapp",
            "mypy>=1.10.0",
            "black>=24.1.0",
            "ruff",
            "types-click",
            "types-PyYAML",
            "types-setuptools",
        ]
    },
    python_requires=">=3.9",
)
