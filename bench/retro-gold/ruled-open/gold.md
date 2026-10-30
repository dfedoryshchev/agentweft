nothing failed.

## change first
- none

## docs
- none listed

FACTS
fact:
  scope: logcount/filters.py
  kind: why
  label: important
  claim: since compares aware datetimes in their own offset and never converts a bound to UTC first, as the lead ruled; whether that holds outside CPython is open
  why: converting 0001-01-01T00:00:00+01:00 to UTC raises OverflowError, so the ruling keeps the comparison on aware datetimes, and the worker's change meets it
  source: seq 2 planner.md; evidence: decisions.md 2026-10-28 10:15
  anchor: logcount/filters.py:8-9
END FACTS
