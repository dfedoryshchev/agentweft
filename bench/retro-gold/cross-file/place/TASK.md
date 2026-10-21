# logcount: count and summarise log lines

## 1. errors
every user-facing error is raised as LogcountError; its text is the part after "error: ".
cli.py catches it and prints it once, as one stderr line, then exits 2.

## 2. output
every command's output goes through output.emit(lines, path=None); --output writes the same bytes to a file.

## 3. filters
--level keeps the lines at that level or above.

## 4. stats
p<N> is the nearest-rank percentile: rank = ceil(N / 100 x count), 1-based, on the sorted values.
never round() the rank: round() rounds half to even.

## modules
logcount/errors.py   LogcountError, the one error type
logcount/output.py   emit(lines, path=None): writes every command's output
logcount/reader.py   read_inputs(paths): yields lines, raises on an unreadable file
logcount/stats.py    nearest_rank(values, p) and the summaries built on it
logcount/cli.py      parses the arguments, runs one command, prints an error once
