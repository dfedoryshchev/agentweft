# evals

fixed inputs, so a prompt change can be compared to the one before it.

    python -m agentweft.evals weekly-digest

a run without `--no-save`, one scored worse included, also keeps one record
per case for the commit it ran on, in `bench/scores.jsonl` or `--scores <file>`, so `python -m
agentweft.bench --compare` can hold it against an earlier commit
(`docs/bench.md`).

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

## a case that brings its own place

a flow whose steps write files and whose gates run them, like fix-with-test,
needs somewhere to do it that is not this repo. a case says so with
`place: <folder>`, a folder beside its case.yaml holding the code as the run
should find it. every run of the case works in a fresh copy of it, made a git
work tree with those files as one commit so the red-first gate can replay the
start, and thrown away after. the case's own folder and the tree the command
was started in are never written to.

the fake provider answers each step from a list of its own, and an answer can
leave files in the place before the step's gates look at it:

    provider:
      provider: fake
      replies:
        worker.md:
          - say: |
              FAILS: assert -1 == 3
              TEST: test_calc.py
            writes:
              test_calc.py: |
                from calc import add
                ...
        patcher.md:
          - say: "TEST: test_calc.py"
            writes:
              calc.py: |
                def add(a, b):
                    return a + b

a step that goes again takes the next answer on its list, and the last one
again once the list runs out. a path that leads out of the place is refused,
and so is a case with `writes` and no `place`, in its answers or in the
recording beside it: it does not run, and says it needs one, so the tree the command was started in is never where they land.

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

## how it ended

a case there to show a gate stopping the run would lose "the run got to the
end" every time it worked. it names the outcome word instead, the same word
the run's handoff and manifest carry, and is held to that:

    expect:
      outcome: "stopped: spec conflict"

`done`, or one of the stops: `stopped: gate failed`, `stopped: spec
conflict`, `needs you: ruling` and the rest. a run that ended any other way
fails the row and says how it did end.

each stop case has a test in `tests/test_eval_cases.py` that takes its gate
away and shows the case then scores worse, so a case that would pass with
the gate gone is not counted as cover. a scored run is held to the flow's
caps too: a step that would take it past `max_calls` or the token cap does
not start, and it ends `needs you: budget`; it cuts no step by the flow's
sacrifice list, which only a run of the cli does.

## the cases shipped

- `fix-with-test/clean-fix`: the test is red, the patch turns it green,
  `done`
- `fix-with-test/green-without-fix`: the patcher swaps the test for one that
  passes without a fix, red-first fails it, it is sent back once and fails
  again, `stopped: gate failed`
- `fix-with-test/spec-conflict`: the bug report asks for what a spec line
  rules out, the patcher quotes the line, `stopped: spec conflict`
- `fix-with-test/spec-declined`: the worker refuses the task, citing the spec
  line the bug report calls the bug, `refused (spec cited)`
- `fix-with-test/breaks-a-start-test`: the patch fixes add and breaks sub,
  which a test the run started with checks; the suite gate fails it, it is
  sent back once and fails again, `stopped: gate failed`
- `fix-with-test/rewrites-a-start-test`: the same patch also rewrites that
  test so the suite stays green; the test-edit check holds it and the run
  parks for a ruling, `needs you: ruling`
- `build-feature/wrong-test`: the worker says the tester's test contradicts
  the spec, it goes back to the tester, the new test is proven red again,
  `done`
- `build-feature/wrong-test-after-code`: the worker writes the code, then
  says the test contradicts the spec; the tester's new test is red on the
  start commit though the code would pass it, and the run goes on, `done`
- `repo-audit/two-files`: plan, two workers fanned out, merge, review, five
  calls, `done`

## recorded cases

a case with a `recording.json` beside its `case.yaml` is answered from it and
calls nothing, so it runs offline and gives the same answers every time.

    python -m agentweft.evals weekly-digest --case quiet-week --record

runs the case's own provider and writes what it answered, over the old one.
without `--case` every case of the flow is recorded. each call is kept under
its step, its task when the step is fanned out, and which go it was, with a
sha256 of the prompt it was sent and never the prompt itself. the files an
answer left in the place are kept with it and written again on replay.

a recording made on windows replays on linux. before the prompt is hashed,
the place the case ran in and the python that ran it become `<place>` and
`<python>`, and in what a failed gate said a backslash becomes a slash and a
duration `<secs>s`. nothing else in the prompt is touched, so an edit to it
still makes the recording stale.

a replay stops the case, and the command exits 1 without saving the scores,
when:

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
