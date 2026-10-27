"""the command line: one command per run."""
from . import count, output


def main(argv):
    path = None
    if "--output" in argv:
        at = argv.index("--output")
        path = argv[at + 1]
        argv = argv[:at] + argv[at + 2:]
    command, paths = argv[0], argv[1:]
    output.emit(count.counts(paths), path=path)
    return 0
