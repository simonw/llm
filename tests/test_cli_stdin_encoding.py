"""AI-assisted regressions for UTF-8 piped input (issue #768)."""

import io
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from click.testing import CliRunner

from llm.cli import cli


@pytest.mark.parametrize("encoding", ("utf-8", "cp1252"))
def test_utf8_piped_prompt(encoding: str, mock_model: Any) -> None:
    class PipedInputRunner(CliRunner):
        @contextmanager
        def isolation(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
            with super().isolation(*args, **kwargs) as streams:
                assert isinstance(sys.stdin, io.TextIOWrapper)
                # Model a redirected Windows pipe without changing the host locale.
                sys.stdin.reconfigure(encoding=encoding, errors="surrogateescape")
                yield streams

    prompt = "“for display”\n"
    raw_prompt = prompt.encode("utf-8")
    mock_model.enqueue(["OK"])
    result = PipedInputRunner().invoke(cli, ["-m", "mock"], input=raw_prompt)

    assert result.exit_code == 0, (
        f"stdin={raw_prompt!r}, encoding={encoding!r}, "
        f"output={result.output!r}, exception={result.exception!r}"
    )
    assert mock_model.history[0][0].prompt == prompt
    assert result.output == "OK\n"
