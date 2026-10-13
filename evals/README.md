# evals

fixed inputs, so a prompt change can be compared to the one before it.

    python -m agentweft.evals weekly-digest

a case is a folder under `evals/<flow>/cases/`: an `inbox/` of files and a
`case.yaml` saying what has to hold. there is no expected output. the output is
not deterministic and a golden file would be wrong by wednesday.

a case for a flow that takes a task (`{TASK}` in its words) gives it as
`task: <text>` in case.yaml or, for anything longer, a UTF-8 `task.md` in the
case folder; not both. a case missing the task its flow needs, or giving one
to a flow with no place for it, scores as a run that did not get to the end.

what a case asserts is the flow's own promises - the same invariants the runner
already checks - plus that the run got to the end, plus what it cost. a run
stopped by a gate, or by a step that produced nothing, loses that one.

## recorded cases

a case with a `recording.json` beside its `case.yaml` is answered from it and
calls nothing, so it runs offline and gives the same answers every time.

    python -m agentweft.evals weekly-digest --case quiet-week --record

runs the case's own provider and writes what it answered, over the old one.
without `--case` every case of the flow is recorded. each call is kept under
its step, its task when the step is fanned out, and which go it was, with a
sha256 of the prompt it was sent and never the prompt itself. a replay stops
the case, and the command exits 1 without saving the scores, when:

- a prompt changed since it was recorded: `recording is stale: planner.md
  prompt changed`. record it again once the change is meant
- the run makes a call the recording has no answer for
- the recording holds an answer the run never asked for

a replayed case says `replayed` on its line of the table.

## the comparison

the last scores are kept in `evals/.last.json` and every run prints what
changed:

    since the last scored run:
      quiet-week          same   (2/2 -> 2/2)
      busy-week           WORSE -1  (2/2 -> 1/2)  tokens +4100

that is the number i did not have for the first year of this. every prompt
change before it was judged by reading one output and deciding it looked
better.

`--no-save` runs without overwriting the baseline.
