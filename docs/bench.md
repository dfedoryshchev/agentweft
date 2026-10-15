# bench

the evals hold a flow's promises on fixed inputs. the bench asks the other
question: given a real task on a real project, did the run get it right? the
run's own tests cannot answer that, it wrote them. a suite it never saw can.

    python -m agentweft.bench bench/example --k 2
    python run.py bench bench/example --k 2

## a set

a set is a folder:

    bench/example/
      bench.yaml          flow, provider, k
      repo/               the project every task starts from
      total-spent/
        TASK.md           the request the run is given
        hidden/           the suite that scores it
      zero-amount/
        TASK.md
        task.yaml         kind: probe
        hidden/

a task may carry a `repo/` of its own; without one it starts from the set's.
`TASK.md` in a task folder is the request; a `TASK.md` inside the project is
the project's spec, the one `build-feature` reads.

a task with no tests under `hidden/` refuses the whole set before anything
runs. a task without a hidden suite has no score, and a set scored on the
tasks that happen to have one is not the set.

## what a run sees

each run works on a fresh copy of the project in a temporary folder, with the
request as its task. `hidden/` is never copied there and `TASK_REPO` is not
set while the run's steps work. once the run has ended, the hidden suite is
copied out on its own and run against what the run left, with `TASK_REPO`
pointing at it, so the tests import the project from there:

    sys.path.insert(0, os.environ["TASK_REPO"])
    import ledger

the copy keeps the suite out of the run's place, not out of the machine: a
provider with a shell that goes looking above its folder can still find the
set. a set meant as a holdout is kept somewhere the run is not pointed at.

## the score

the hidden suite runs once on the project as it starts and once per run. each
run gets a row:

- `outcome`: the run's one outcome word (`docs/journal.md`), read off the cause
  its record names, never off what a step said
- `finished`: the outcome is `done`
- `core_correct`: every hidden case green. on a probe, a recorded refusal
  (`refused (spec cited)`, `stopped: spec conflict` or `needs you: ruling`)
  with no guard gone red; a probe the run did nothing on and then failed a
  gate does not count
- `false_success`: finished, on a task that is not a probe, with a hidden case
  red
- `false_refusal`: one of those three refusals on a task that is not a probe
- `probe_stop`: on a probe, the outcome it stopped with
- `red_first`: `proven` when a red-test or red-first gate ran and held,
  `failed` when one did not, `no gate` when the flow ran none
- `tests_added` and `pins`: the test files the run added, and those of them
  that pass on the project as it started. a pin would not have caught the
  change missing
- `hidden`: cases, how many were red at the start, how many of those it fixed,
  which are red now and which were green at the start and are red now
- `usd`, `calls`, `tokens`, `wall`
- `key`: what produced it, the same key the evals keep: the model at each
  step, a digest of the prompts and the flow file, and the settings that
  change what runs

the summary under the table counts the rows, gives the correct rate of each
repeat on its own so the run-to-run spread shows beside the total, and the
cost per correct result: every attempt's money, the failed and the refused
included, over the correct ones. no correct run is `none correct`, and a run
without a price makes it `unpriced` rather than a smaller number.

the rows and the summary go to `runs/bench/<set>-<when>.json`, or `--out`.

## providers

the example set runs on the fake provider, which answers without asking
anything and edits nothing, so every row there scores wrong. it shows the
command end to end, not a flow's quality. a set that names any other provider,
or none so the flow's own is used, is refused unless the command says
`--live`, because that calls a model and is charged.

## flags

- `--k <n>` runs per task, over `k:` in bench.yaml, 1 by default
- `--flow <flow>` the flow, over `flow:` in bench.yaml
- `--out <file>` where the scores are written
- `--live` let the set's provider call a real model
