# the journal, and picking a run back up

## what gets written

every run appends one line to `runs/journal.md`:

    2026-01-22 09:14  weekly digest  ok  42s  weekly-digest-2026-01-22-1.md
    2026-01-22 18:02  ops-check  failed at reviewer.md  11s

and every step's output lands under `runs/<flow>-<date>-<time>/`, one file per
step, as it is produced.

flows that run several times an hour set `journal: false` - code-review does.
they still write their step outputs, they just stay out of the weekly number.

## the week

    python rollup.py

reads the journal for the last 7 days: runs, failures, average duration, per
flow.

## when a run dies

    python run.py weekly-digest --resume

finds the most recent failed run for that flow in the journal, works out which
steps are left, and hands the first of them whatever the step before it
produced last time. that is why the step outputs are on disk - without them
resume could tell you where it died and nothing more.

    python run.py weekly-digest --resume weekly-digest-2026-01-22-1

picks a specific run instead of the most recent.

## reading it from an agent

`python mcp_server.py` exposes the journal, the weekly rollup, the gate results
and every recent run as resources. see `docs/mcp.md`. that turned out to be the
half of mcp i use.

## what it does not do

a resumed run writes its own journal line. so a run that failed and was picked
up shows twice.
