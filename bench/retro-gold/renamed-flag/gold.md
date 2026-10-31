nothing failed in this run.

## change first
- none

## docs
- README.md: ticket

FACTS
fact:
  scope: README.md
  kind: nice-to-do
  claim: the line on writing the counts to a file still says --file; the flag is --output now
  why: seq 1 worker.md renamed the flag in logcount/cli.py, as TASK.md 1 asks, and the README still named the old one
  source: seq 1 worker.md; evidence: README.md:7 "pass --file out.txt to write the counts to a file instead of stdout."
END FACTS
