from setuptools import setup
import os

VERSION = "0.3"


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
    packages=["llm"],
    entry_points="""
        [console_scripts]
        llm=llm.cli:cli
    """,
    install_requires=[
        "click",
        "openai",
        "click-default-group-wheel",
        "sqlite-utils",
    ],
    extras_require={"test": ["pytest", "requests-mock"]},
    python_requires=">=3.7",
)
