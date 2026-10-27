"""every command's output, to stdout or a file."""
import sys


def emit(lines, path=None):
    text = "".join(line + "\n" for line in lines)
    if path is None:
        sys.stdout.write(text)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
