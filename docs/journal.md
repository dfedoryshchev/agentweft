# the journal, and picking a run back up

## what gets written

every run appends one line to `runs/journal.md`:

    2026-01-22 09:14  weekly digest  ok  42s  weekly-digest-2026-01-22-1.md
    2026-01-22 18:02  ops-check  failed at reviewer.md  11s
    2026-01-22 18:40  ops-check  parked at planner.md  9s  ops-check-2026-01-22-184011

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

## when a run stops on purpose

a step can say who the run waits for once it is done:

    steps:
      - role: planner
        prompt: planner.md
        pause: user
      - role: worker
        prompt: worker.md

the planner runs, its output is written, its gates are checked, and then the
run stops. the journal says `parked at planner.md` where a death says `failed
at planner.md`, and the run leaves a `handoff.md` next to its step outputs:

    # parked: park-demo-2026-08-27-173348

    waiting for    user
    flow           park demo
    stopped after  planner.md

    nothing failed. planner.md finished and its checks passed. the flow
    asks for user here, so the rest of it has not run.

    ran
      planner.md      0.0s

    left
      worker.md

    what planner.md produced is in runs/park-demo-2026-08-27-173348/planner.md
    read it before carrying on. that file is what the next step gets handed,
    so editing it is how you change what the rest of the run works from.

    to carry on
      python run.py park-demo --resume park-demo-2026-08-27-173348

`--resume` is the same switch either way, and it does the two different things
the two ways of stopping deserve: a run that died starts again AT the step that
died, because that step produced nothing, and a run that parked carries on AT
THE STEP AFTER the one it parked on, because that step finished and the only
thing missing was the person.

the file the handoff points at is the whole gate. the next step is handed
whatever is in it at the moment you carry on, so reading it and leaving it
alone is approval, and editing it is a correction the rest of the run works
from.

`pause` on the last step of a flow does nothing: the run finishes and no
handoff is written. there is nothing behind that step for a person to hold up.

## reading it from an agent

`python mcp_server.py` exposes the journal, the weekly rollup, the gate results
and every recent run as resources. see `docs/mcp.md`. that turned out to be the
half of mcp i use.

## what it does not do

a resumed run writes its own journal line. so a run that failed and was picked
up shows twice.
