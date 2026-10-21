## seq 2 reviewer.md
failed: the reviewer sent the work back: stats still writes stdout in cli.py:14, not through output.emit
why: the responsibility move left one caller, stats in cli.py, on the old path of writing sys.stdout itself
change: logcount/cli.py stats branch - call output.emit with the summary lines

## change first
logcount/cli.py stats branch - call output.emit

FACTS
fact:
  scope: logcount/output.py
  scope: logcount/cli.py
  kind: decision
  label: important
  claim: all output goes through output.emit; cli.py never writes stdout
  why: TASK.md section 2 fixes output.emit; the move missed the stats caller in this run
  source: seq 2 reviewer.md; evidence: TASK.md:8 "every command's output goes through output.emit"
  anchor: logcount/output.py:5-11
guard: seq 2
  kind: test
  where: tests/test_output.py
  what: each command's output equals emit's bytes when --output is given
END FACTS
