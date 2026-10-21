"""the command line: one command per run, one error line at most."""
import sys

from . import count, output, stats
from .errors import LogcountError
from .reader import read_inputs


def main(argv):
    command, paths = argv[0], argv[1:]
    try:
        lines = list(read_inputs(paths))
        if command == "stats":
            output.emit(stats.summary(lines))
        else:
            output.emit(count.counts(lines))
    except LogcountError as e:
        sys.stderr.write("error: " + str(e) + "\n")
        return 2
    return 0
