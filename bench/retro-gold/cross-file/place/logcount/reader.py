"""the lines of every input file, in order."""
from .errors import LogcountError


def read_inputs(paths):
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                yield from f.read().splitlines()
        except OSError:
            raise LogcountError("cannot read " + path)
