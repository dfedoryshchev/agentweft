## seq 3 worker.md
failed: the command gate: tests/test_parse.py::test_unreadable_one_line saw 2 stderr lines for an unreadable file, wanted 1
why: logcount/reader.py printed its own error line instead of raising LogcountError; the unification missed one module
change: logcount/reader.py read_inputs - raise LogcountError on an unreadable file, never print

## change first
logcount/reader.py read_inputs - raise, never print

FACTS
fact:
  scope: logcount/
  kind: convention
  label: important
  claim: user-facing errors are raised as LogcountError and printed once by cli.py
  why: TASK.md section 1 fixes one stderr line; reader.py printing broke it in this run
  source: seq 3 worker.md; evidence: TASK.md:4 "every user-facing error is raised as LogcountError"
guard: seq 3
  kind: test
  where: tests/test_cli.py
  what: every command on an unreadable file prints exactly one stderr line
END FACTS
