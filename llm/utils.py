import click
import contextlib
from typing import List, Dict


def dicts_to_table_string(
    headings: List[str], dicts: List[Dict[str, str]]
) -> List[str]:
    max_lengths = [len(h) for h in headings]

    # Compute maximum length for each column
    for d in dicts:
        for i, h in enumerate(headings):
            if h in d and len(str(d[h])) > max_lengths[i]:
                max_lengths[i] = len(str(d[h]))

    # Generate formatted table strings
    res = []
    res.append("    ".join(h.ljust(max_lengths[i]) for i, h in enumerate(headings)))

    for d in dicts:
        row = []
        for i, h in enumerate(headings):
            row.append(str(d.get(h, "")).ljust(max_lengths[i]))
        res.append("    ".join(row))

    return res


class NullProgressBar:
    def __init__(self, *args):
        self.args = args

    def __iter__(self):
        yield from self.args[0]

    def update(self, value):
        pass


@contextlib.contextmanager
def progressbar(*args, **kwargs):
    silent = kwargs.pop("silent")
    if silent:
        yield NullProgressBar(*args)
    else:
        with click.progressbar(*args, **kwargs) as bar:
            yield bar
