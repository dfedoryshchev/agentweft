import sys

from .runner import main
from .runner.cli import COMMANDS


def entrypoint():
    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        return COMMANDS[sys.argv[1]]()
    return main()


if __name__ == "__main__":
    sys.exit(entrypoint())
