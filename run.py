import sys

from runner import main
from runner.cli import COMMANDS

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        sys.exit(COMMANDS[sys.argv[1]]())
    sys.exit(main())
