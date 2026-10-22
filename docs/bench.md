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

- `outcome`: the run's one outcome word (`docs/journal.md`), read off the
  cause its record names, never off what a step said. a decline ends the run
  with no stop reason and is still read off its record. `needs you: ruling` is
  a park on the question the step's own answer asked, or on a `VERDICT: spec
  change request` its prompt lists; a park on anything else, a fence, a spec
  line the run rewrote, a cause nobody could root, is `needs you: no ruling
  asked`
- `finished`: the outcome is `done`
- `core_correct`: every hidden case green. on a probe, a recorded refusal
  (`refused (spec cited)`, `stopped: spec conflict` or `needs you: ruling`)
  with no guard gone red, missing or broken, and at least one guard green at
  the start; a probe the run did nothing on and then failed a gate, or parked
  with no ruling asked, does not count
- `false_success`: finished, on a task that is not a probe, with a hidden case
  red or missing
- `false_refusal`: one of those three refusals on a task that is not a probe
- `probe_stop`: on a probe, the outcome it stopped with
- `red_first`: `proven` when a red-test or red-first gate ran and held,
  `failed` when one did not, `no gate` when the flow ran none
- `tests_added` and `pins`: the test files the run added, and those of them
  that pass on the project as it started. a pin would not have caught the
  change missing
- `hidden`: cases, how many were red at the start, how many of those it fixed,
  which are red now and which were green at the start and are red now, or are
  gone. a case gone by the end, its file no longer importable or skipped, is
  regressed, red at the start or green, and a file that cannot be collected at
  all fails the run. a suite that runs past 600 seconds is one red case,
  `::timed out after 600s`, everything it started is ended with it, and the
  bench goes on to the next run. a suite
  that runs no case at all (a conftest that raises, a usage error, nothing
  collected) is one red case too, `::no case ran, pytest exited <code>`
- `usd`, `calls`, `tokens`, `wall`
- `key`: what produced it, the same key the evals keep: the model at each
  step, a digest of the prompts and the flow file, and the settings that
  change what runs

the summary under the table counts the rows, gives the correct rate of each
repeat on its own so the run-to-run spread shows beside the total, and the
cost per correct result: every attempt's money, the failed and the refused
included, over the correct ones. no correct run is `none correct`, and a run
without a price makes it `unpriced` rather than a smaller number.

the rows and the summary go to `runs/bench/<set>-<when>.json`, or `--out`,
written again after each run, so a bench that dies keeps the runs it paid
for.

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
- `--scores <file>` where the records kept per commit go, `bench/scores.jsonl`
  by default
- `--live` let the set's provider call a real model
- `--mutants` score each added test by the mutants of the fix it kills

## scores per commit

a score on its own says nothing about the commit before it. after every bench,
and every eval run without `--no-save`, a run scored worse than the last one
included, one record per task and repeat is
appended to `bench/scores.jsonl`, or `--scores <file>`. a file inside `runs/`
is refused: runs are cleared, and the records are what outlives them. git
ignores `bench/scores.jsonl`, so the records stay with the machine that ran
them. each record is one JSON line:

- `sha`: the commit checked out when it ran
- `dirty`: a tracked file differed from that commit. the scores file itself
  is not counted
- `source`: `bench` or `eval`, and `set`, the bench set it came from
- `flow`, `task` (an eval's case) and `repeat`
- `outcome`: `pass` (core correct, or every promise kept), `finished` (got to
  the end without passing) or `stopped`
- `score` and `of`: hidden cases green over cases, or promises kept over
  promises checked
- `usd`, `tokens`, `seconds`
- `replayed`: an eval case answered from its recording. a bench run is never
  replayed

outside a git tree nothing is kept, and the command says so. an eval whose
recording does not match the run keeps nothing either.

    python -m agentweft.bench --compare
    python -m agentweft.bench --compare --base 1a2b3c4 --head 5d6e7f8

holds the head, HEAD by default, against the base: the one named, or the
nearest earlier commit with records. a sha may be shortened. `--flow` keeps
one flow and `--scores` reads another file. records made with uncommitted
changes are not that commit's score, so neither side counts them, and each
side says how many it left out.

the report gives each side's N (tasks) and k (repeats), then one line per
task: `worse`, `better` or `same`, the passes over the repeats on each side
(a single repeat is its outcome word, never a rate), and how to read it:

- `replayed, no noise`: both sides answered from recordings, so any move is
  the code's
- `inside the noise of k <n>`: the move is no larger than twice its standard
  error, the pass rate pooled over both sides' repeats. a pass at k 1 turning
  into a fail is always inside it
- `no record on head` or `new, no record on base`: a missing record is never
  read as a pass

it exits 1 when a task that passed on any repeat of the base fails on every
repeat of the head, when such a task has no record on the head, when either
side has no record at all, and when a line of the file is not a whole record.

## mutants

a pass count cannot show that sixteen new tests all guard the same one line.
`--mutants` breaks the run's fix on purpose and reads which tests notice.

the mutants cover the changed lines of the source the run changed, never the
whole module, and no model is asked:

- `unpatch`: the fix taken out whole
- `hunk <file>:<line>`: one hunk of the fix taken out
- up to 20 small edits of a changed line: a comparison flipped (`<` to `<=`,
  `==` to `!=`), a whole number one up or one down, a condition negated, a
  statement deleted, a statement swapped with the next one. past 20, a seeded
  pick of 20

a mutant that reads the same as the fix or as an earlier mutant is dropped.
each test the run added or changed runs against each mutant on a copy of the
place, one pytest per test file, so a mutant that breaks one file's import
kills only that file's tests. the mutants it fails on are its kill signature.
the same place gives the same mutants, in the same order. when no new test
is green with the fix, no mutant runs. a folder named build, dist, venv and
the like is left out inside the place, never because of where the place is.

the tests the project started with, the suite the new ones joined, run
against each mutant too. a mutant one of them kills was caught already, so a
new test's own kills, its unique kills, are only the mutants nothing in that
suite kills. a new test whose every kill the suite makes already adds a pass
count and no catch.

the row gets `mutants`, and the report a section per run:

- `tests`: each test green with the fix, and the mutants it kills
- `signatures`: how many distinct signatures there are
- `duplicates`: the likely duplicates, groups of tests whose signatures are
  alike. sixteen tests that die on the same deleted line are one group
- `undecided`: the same groups when fewer than `minimum` mutants (8) are
  killed by any test. a mutant no test kills cannot tell two tests apart, so
  it does not count. two different tests can kill the same few mutants by chance,
  so the report says not enough mutants to judge instead. a test that kills
  nothing is never in a group
- `pins`: tests green without the fix that kill nothing
- `red_with_fix`: tests that fail with the fix, so kill nothing that can be
  read
- `duplicate_at`: the threshold, shared kills over all kills, at which two
  signatures count as one. 1.0, the same set, by default
- `minimum`: how many mutants some test kills that a run needs before a
  shared signature is called a likely duplicate
- `judged`: how many mutants some test green with the fix kills
- `suite`: how many of the tests the project started with pass with the
  fix, and `suite_kills` the mutants they kill
- `unique`: each new test and the mutants it kills that the suite does not;
  `unique_kills` how many mutants only the new tests kill. the report lists
  the tests with no kill of their own

a shared signature is a lead, not proof. the report only labels: no test is
deleted or skipped because of it.

the summary adds the threshold, the minimum, the signatures, the likely
duplicate tests and the undecided ones (each group past its first), the
pins, the unique kills and the tests with no kill of their own.

## the retro's gold

the retro reads a run's record and names what failed, why, what to change and
the fact the project should keep. `--retro` holds it to a gold, asking the
retro role alone on a recorded run (step mode), so a model and an effort can
be tried on it without running a flow:

    python -m agentweft.bench --retro bench/retro-gold --k 3 --live

each case is a folder:

    bench/retro-gold/cross-file/
      record/             steps.jsonl, handoff.md and diff.patch as a run
                          wrote them, with one failed attempt whose cause is
                          in the record
      place/              the project as the run left it; the retro reads it
                          with the read grant a run gives it
      gold.md             the answer a careful reader writes for the record
      gold.yaml           what the program checks the answer on

the four cases cover the changes a retro has to see through: one convention
unified across several files with one module missed (`cross-file`), a
responsibility moved to a new module with one caller left behind (`shift`),
an option carried through layers that stopped one short (`layered`), and an
extraction with no change in behaviour that changed one (`refactor`).

the prompt is the one a run hands the retro, built by the same code from the
record. an answer scores one for each of:

- `failed`: a `## seq <n> <step>` section for the attempt `gold.yaml` names
- `cause`: that section's `why:` line holds every word `cause` lists
- `change`: that section's `change:` line names the `change` file
- `fact`: the FACTS block parses and has a fact or supersession of the gold's
  kind with one of the gold's scopes, one the runner would write: held to a
  copy of the case's `place/` and a record read from `record/steps.jsonl`
  (`docs/guardrails.md`, "the facts only the runner writes"), so a fact with
  evidence the record does not back, or no why, scores nothing

a change sent to the wrong file scores 0 whatever else it got right. a case
passes when every one of the k repeats scores 4; the gold itself scores 4 on
every case, and a test holds it there. each row keeps `reader`, None until a
blind reader gives the change text and the fact's why 0 to 2.

the provider is `provider:` in the folder's `bench.yaml`; one that calls a
real model runs only with `--live`. the scores go to `--out`, or to
`runs/bench/retro-<set>-<time>.json`, with a row per case and repeat (the
four items, the score, the answer, its cost when the provider said, its
`tokens` counted the way a step's line counts them, `{"counted": false}` when
the provider said none, and the `seconds` the answer took) and the summary:
cases, cases passed, k.

## a second run on the same repo

a bench set runs each task once on a fresh project, so it never shows what
the facts one run leaves (`journal.md`, "what is known about a file") save
the next. `--pairs` runs two related tasks one after the other on the same
project:

    python -m agentweft.bench --pairs <set> --k 2 --twin --live

a pair is a folder:

    <set>/errors/
      first.md          the task that leaves facts behind (run 1)
      second.md         a related task on the same files (run 2)
      hidden/           the suite run 2 is scored on, never seen by a run
      repo/             the project both runs start from, or the set's repo/
      gold.yaml         what run 1 should leave, and what run 2 is held to

`gold.yaml` is written before anything runs:

    trail:                      the facts a careful retro keeps after run 1
      - scope: [pkg/]
        kind: convention
    false:                      a fact on one of these scopes whose claim
      - scope: [pkg/cli.py]     holds every word is one the record does not
        words: [prints]         back
    convention:                 the project's documented way run 2 follows
      scope: [pkg/]
      check: [python, check.py]

the check runs in the pair's folder with `TASK_REPO` naming the place, the
way the hidden suite does, so the project a run sees never holds it; exit 0
is the convention held. a pair with no convention scope or check, no
`second.md` or no hidden suite refuses the whole set before anything runs.

each repeat runs run 1 on a fresh copy of the project, then run 2 on what run
1 left: the `lane` arm, handed the facts run 1 kept. `--twin` also runs run 2
on a copy of what run 1 left without the store's `.md` files under `facts/`
(a project's own file there stays), with the flow copied and `lane: off`
added (the `twin` arm): no fact is handed to a step and none is on disk for
a step to open, so the two arms differ in the facts alone. a copy that still
holds a store file stops the bench before run 2. the flow has to run
the retro (every shipped flow does), or run 1 keeps nothing.

a row per pair and repeat holds:

- `first`: run 1's outcome, how many new facts its retro had the runner
  write (`facts_written`) and how many more the per-run cap refused
  (`facts_capped`), how many of the gold's `trail` they
  match by scope and kind (`trail_found` of `trail`), the ids of the ones the
  gold names false, its cost, seconds and each step's seconds, tokens and
  cost
- `second.lane` and `second.twin`: run 2's outcome, finished and correct on
  the hidden suite (green at the start is what run 1 left), the files it
  changed, the facts each step was handed (`facts_attached`, step and id) and
  the ones the run's change reached (`facts_used`: a fact whose scope holds
  for a changed file; read from the whole run's diff, as a step's own diff is
  not kept), and the convention: `honoured` or `contradicted` by its check
  when the change reached the convention's scope, `untouched` when it did
  not, `not checked` when the check could not run or ran past the suite's
  limit, never a pass

the summary gives each arm's correct, finished, conventions, cost and wall,
and the probation rules, set before any pair ran:

- no run proposes more than 3 new facts, counting the ones written and the
  ones the per-run cap refused (`facts_capped` on each run's row): a run
  that does is counted as spam, though the cap let only 3 through
- at least one in 4 attached facts is used by the run it was handed to
  (`none attached` when no fact was handed, which is not judged)
- no fact the gold names false is written: one is printed as `the write path
  is killed until fixed`

and `probation holds` or `probation fails`. the scores go to `--out`, or to
`runs/bench/pairs-<set>-<time>.json`, written again after each repeat so a
bench that dies keeps what it scored.
