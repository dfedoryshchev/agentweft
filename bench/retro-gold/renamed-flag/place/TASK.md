# logcount: count and summarise log lines

## 1. output
every command's output goes through output.emit(lines, path=None).
--output <path> writes the same bytes to a file. it replaces --file, which is gone.

## modules
logcount/output.py   emit(lines, path=None): writes every command's output
logcount/cli.py      parses the arguments, runs one command
