import sys

from agentweft.runner import main
from agentweft.runner.cli import COMMANDS, command

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        sys.exit(command(sys.argv[1]))
    sys.exit(main())
