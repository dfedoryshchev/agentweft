# decisions

## 2026-10-28 10:15  planner.md decided for worker.md: a T whose UTC value falls before year 1 is valid and compared as an instant, never converted to UTC first

asked by worker.md in build-feature-2026-10-28-101200:

NEEDS: --since with 0001-01-01T00:00:00+01:00, whose UTC value falls before year 1. TASK.md 2 makes it a valid T, and nothing says how it compares.

decided:

DECIDED: a T whose UTC value falls before year 1 is valid and compared as an instant, never converted to UTC first
why: TASK.md 3 compares times as instants; converting 0001-01-01T00:00:00+01:00 to UTC raises OverflowError, so the comparison stays on aware datetimes in their own offset.

decided by planner.md, the flow's lead, before the operator was asked
