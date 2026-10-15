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
already checks - plus that the run got to the end, plus what it cost, plus
the steps it took when the case says which (below). a run
stopped by a gate, or by a step that produced nothing, loses that one.

## the steps it took

a right answer reached the wrong way scores like a right answer, so a case can
also say which steps ran and how many calls the run made. both are read off
the run's own `steps.jsonl`, never off what a step said:

    expect:
      invariants: all
      steps:
        match: strict
        path:
          - planner.md ok -> worker.md
          - worker.md ok -> merge.md
          - merge.md ok -> reviewer.md
          - reviewer.md ok  PASS length  PASS regex
      calls: 6

a line of `path` is a pass at a step as the golden runs in `tests/golden/`
write it, without the number: the step, its outcome, where it sent the work,
then every gate it ran. it may stop at any word, so `reviewer.md` is any pass
at the reviewer and `reviewer.md gate failed` one a gate stopped. `match` is
one of the four trajectory match modes of agentevals, `strict` when not given:

- `strict`: these passes in this order and no others
- `unordered`: these passes and no others, in any order
- `superset`: every one of these ran, and others may have too. a case that
  passes only if the gate ran says it this way
- `subset`: nothing ran that is not one of these, so a run that stopped
  never went on past the step that stopped it

each mode counts, so two `worker.md` lines want two passes at the worker. a
case that fails one says the mode and the passes:

    FAIL the steps it took (superset) - missing merge.md

these hold the runner's own path - the steps, the redos, the gates - and
not anything a model did inside a step.

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

## what produced a score

every score is kept with what produced it, and the table prints it under the
case's line:

      by api m-1 at every step, prompts 3f9a0c1d2e4b, investigate off, verify off

- the model at each step: the provider and the model id the reply named, or
  the one it was asked for when the reply named none. a replayed case names
  the provider in its case.yaml, the one that recorded it
- a sha256 over every file a step's words come from: the flow's own prompt
  files, the role library, the fragments and the skills
- a sha256 of flow.yaml
- the `investigate:` mode, and whether a verify judge runs
- the day it was scored

two scores produced differently are not a better or a worse score, they are
an A/B, and the comparison says on what:

      quiet-week          A/B on model at reviewer.md  (2/2 -> 1/2)
      busy-week           A/B on investigate; prompts  (2/2 -> 2/2)

a step that ran in only one of the two runs is not a model change; a
flow.yaml edit that changed none of the above is an A/B on flow. a score kept
before scores carried any of this is compared as before.

`--no-save` runs without overwriting the baseline.

## when the command fails

a case that passes fewer promises than last time, produced by the same model,
prompts and settings, fails the command: it exits 1 and the scores are not
saved, so running it again does not wash the drop out of the baseline.

    two-files: scored worse than the last run by the same model, prompts and
    settings, so the command fails and these scores are not saved. --accept
    keeps them as the new baseline

an A/B never fails the command, whichever way it went, and the comparison
says so under its lines. a replayed case gives the same answers every time,
so any drop on replay is a change in the code, never noise. `--accept`
saves a worse score as the new baseline when the drop is meant.
