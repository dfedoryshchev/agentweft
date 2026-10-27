nothing failed in this run.

## change first
- none

## docs
- README.md: edit

FACTS
edit: README.md
  now: pass --file out.txt to write the counts to a file instead of stdout.
  after: pass --output out.txt to write the counts to a file instead of stdout.
  because: seq 1 worker.md renamed the flag in logcount/cli.py, as TASK.md 1 asks, and the README still named the old one
END FACTS
