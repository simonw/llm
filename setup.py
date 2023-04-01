from setuptools import setup
import os

VERSION = "0.1"


def get_long_description():
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md"),
        encoding="utf8",
    ) as fp:
        return fp.read()


setup(
    name="llm",
    description="Access large language models from the command-line",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Simon Willison",
    url="https://github.com/simonw/llm",
    project_urls={
        "Issues": "https://github.com/simonw/llm/issues",
        "CI": "https://github.com/simonw/llm/actions",
        "Changelog": "https://github.com/simonw/llm/releases",
    },
    license="Apache License, Version 2.0",
    version=VERSION,
    packages=["llm_cli"],
    entry_points="""
        [console_scripts]
        llm=llm_cli.cli:cli
    """,
    install_requires=["click", "openai", "click-default-group-wheel"],
    extras_require={"test": ["pytest"]},
    python_requires=">=3.7",
)
