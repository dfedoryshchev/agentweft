# the journal, and picking a run back up

## what gets written

every run appends a `running` line to `runs/journal.md` before its first
step, and one more line when it ends:

    2026-01-22 09:14  weekly digest  running  0s  weekly-digest-2026-01-22-091402
    2026-01-22 09:14  weekly digest  ok  42s  weekly-digest-2026-01-22-091402  weekly-digest-2026-01-22-1.md  5 calls, 600 tokens counted (input 500, output 100), $0.0010 priced, reported $0.0010 (cli x5)  weekly-digest-2026-01-22-091402/handoff.md
    2026-01-22 18:02  ops-check  failed at reviewer.md  11s  ops-check-2026-01-22-180207  gate failed  3 calls, ~900 tokens estimated, unpriced: no model named x3 (cli x3)  regex: no line starts with "- ["  ops-check-2026-01-22-180207/handoff.md
    2026-01-22 18:40  ops-check  parked at planner.md  9s  ops-check-2026-01-22-184011  parked  1 call, ~300 tokens estimated, unpriced: no model named x1 (cli x1)  waiting for user  ops-check-2026-01-22-184011/handoff.md

the columns are split by two spaces: when the run started, the flow, how it
ended, how long it took, the run id. a finished run then has the file it
saved and what it spent; a stopped run has its cause, what it spent and why.
the last column on either points at the run's handoff, `runs/<run
id>/handoff.md`, the file to read about the run (below); a resumed run's
lines end with one more, `resumes <run-id>` (see "when a run dies").
what it spent is counted, estimated or mixed, then its money: what the price
table makes of it and what the provider said (see "the spend cap" and "what it
cost in money" in `guardrails.md`). `python run.py spend` prints the last
twenty lines that say, then those runs per flow and per provider, read from
their `steps.jsonl`; a run whose steps were never counted says `estimated only:
no counts, no money` instead of adding up to nothing.

a run saves its output as `runs/<flow>-<day>-<n>.md`, and the first run of a
day is `-1`.

how a run ended is kept in `runs/last-run-<flow>-<key>.json`, the key a hash
of the repo the run worked in (its place when that is in no repo) and its
task. it is written when the run finishes and when it stops short, with the
run id, how it ended, its place and `last_run`, the newest output a run of the
same flow, repo and task saved. a planner is told the absolute path of that
output and nothing else, and only while the file is there and the kept place
is in the same repo, so two projects run from one install never see each
other's runs and a planner never has to search for the file. an older install
kept one file per flow inside the package; it names no task, so it never
gives a planner that line.

## why a run stopped

a run that stops short says `parked at <step>` when it is waiting for someone
and `failed at <step>` otherwise, and its cause is one of a fixed list:

- `gate failed` - a gate failed the step, or the step did not give the router
  what the flow requires of it (an output it must contain, a verdict it can
  read). the why is the gate and what it said.
- `refused` - the step was not allowed to start (the place changed under it)
  or its output was refused (a preflight in `refuse` mode).
- `parked` - the flow asked for a person, a preflight parked, the work ran out
  of redos, or files git cannot give back were changed.
- `provider outage` - the account's own limit refused the call: a session,
  weekly or usage limit. the run parks after that one call, never retries and
  never hands the empty answer to a gate; the why and `handoff.md` say when
  the provider said it resets, or `unknown`.
- `budget` - the call or token cap.
- `exception` - something raised; the traceback is printed as well.
- `interrupt` - Ctrl-C.
- `no answer` - the step came back empty after its retries. the why carries
  the last thing the provider said.

the same cause and why go on the step's line in `steps.jsonl` and into
`runs/<run-id>/why.md`. a cause off the list is refused where the line is
written, and `rollup.py` refuses one it finds.

`run.py` exits 0 when the run finished (or was not due), 1 when it could not
start, 2 when it stopped, and 130 on an interrupt.

## how a run ended

every run that ends has one outcome, for a program to read where the cause
is for counting: `outcome` in `runs/<run-id>/manifest.json` (null while the
run is going), the first words after the run id in `handoff.md`'s heading, and
so the console's end line too. a run that got through is `done`, or `done, 1
check unproven` / `done, <n> checks unproven` when a judge said it could not
decide some checks (`docs/gates.md`, verdict). a stop is the one outcome its
cause maps to:

| cause | outcome |
|---|---|
| `gate failed` | `stopped: gate failed` |
| `refused` | `stopped: guard refused` |
| `parked` | `needs you: ruling` |
| `provider outage` | `waiting: provider limit` |
| `budget` | `needs you: budget` |
| `exception` | `stopped: tool fault` |
| `no answer` | `stopped: tool fault` |
| `interrupt` | `stopped: interrupted` |

the map is `OUTCOME` in `agentweft/runner/stops.py`, with no default: a cause
with no outcome is refused where the outcome is read. a gate that failed
because the step would not do what it was asked still reads `stopped: gate
failed`, so the outcome does not tell a principled stop from a broken step.
the exit codes do not change with it.

and every step's output lands under `runs/<flow>-<date>-<time>/`, one file per
step, as it is produced. `runs/` is the one beside `run.py`, not one in the
directory the run was started from, so `--resume`, `rollup.py` and the mcp
server find the same records from anywhere.

flows that run several times an hour set `journal: false` - code-review does.
they still write their step outputs, they just stay out of the weekly number.
they cannot be resumed: a run that finished is never written down, so the
journal cannot tell it from the last one that stopped, and `--resume` says so
instead of picking a finished run back up.

## what each step did

the journal line is the run. `runs/<run-id>/steps.jsonl` is the steps: one
json line every time a step runs, a redo's second pass included, written
whatever happened next - the run went on, sent the work back, parked, stopped
or crashed. the keys are always all there, in this order:

    {"seq": 1, "time": "2026-01-22T09:14:03", "step": "worker.md",
     "from": null, "to": "reviewer.md",
     "provider": "cli", "command": "claude", "model": "a-model",
     "model_reported": "a-model-1", "model_choice": null, "grant": null,
     "tokens": {"counted": true, "input": 12, "output": 4,
                "cache_read": 2, "cache_creation": 0},
     "cost": 0.25, "priced": 0.25, "cost_from": null, "session": "s-1",
     "seconds": 8.4,
     "cached": false,
     "retries": {}, "background_killed": 0,
     "gates": [{"gate": "length", "ok": true,
                               "detail": "1 lines"}],
     "ungated": false,
     "outcome": "ok", "cause": null, "why": null,
     "file": "steps/001-worker.md",
     "task_file": "task.md", "tasks": null,
     "handoff": {"state": "present", "did": ["calc.py: add returns a + b"],
                 "verified": [{"claim": "1 passed",
                               "cmd": "python -m pytest -q test_calc.py",
                               "saw": "1 passed", "backed": "backed",
                               "why": ""}],
                 "not_verified": [], "assumed": [], "doubts": [],
                 "must_not_miss": ["TASK.md:3 - amounts are exact decimals"],
                 "tried": [], "read": ["calc.py:1-4 - the whole module"],
                 "other": {}}}

(one line on disk; wrapped here.)

- `seq` counts the steps run, from 1. a resumed run carries on from the last
  number of the run it picked up, so the two files read as one sequence.
- `from` is the step whose output this one was handed, `to` the one the run
  went to next: null when nothing came before, and when the run ended or
  stopped here.
- `model` is the id the provider sends, null for one that sends none (the fake,
  or a cli command other than claude). `model_reported` is what the provider
  said answered.
- `model_choice` is what this step's role was asked to run on, null when
  nothing chose and the provider's own model answered:
  `{"role": "reviewer", "asked": "low", "from": "run", "applies": true}`.
  `from` is `run` (`--model-for`), `step` (its `model:`) or `flow` (`tiers:`);
  `applies` is false when the provider cannot act on a model choice (the fake,
  a cli command other than claude), so the choice is written down and was not
  used.
- `grant` is null for a step that declared no `tools`. otherwise it is the
  grant and what was done with it: `{"tools": ["read"], "enforced": true,
  "argv": [...], "cli_version": "2.1.296"}`. `argv` is the command line
  `claude` was started with, minus the command itself (the prompt goes on
  stdin, so nothing of it is in there), which pins the permission mode and
  every flag the grant became; `cli_version` is what `claude --version` said.
  `enforced` is false, `argv` and `cli_version` null, for a provider that was
  handed nothing (the fake, the api, a cli command other than claude).
- `tokens` and `cost` are what the provider reported, summed over every go a
  retry took. `{"counted": false}` and a null cost mean it reported nothing:
  not zero, unknown. a cached answer sent nothing, so it costs 0 and is not
  counted. `priced` is the same tokens through the price table, null when a
  go was not counted or the table could not price it.
- a go that never answered, one that timed out say, stated no cost and was
  paid for all the same. it is in `cost` at the price table's figure: from
  its session's transcript when the cli wrote one, else estimated from the
  prompt (`providers.md`, `metered`). `cost_from` then says how many goes
  each figure came from, `{"provider": 1, "estimate": 1}` for a step whose
  first go timed out and whose retry answered; it is null when every go
  stated its own cost or nothing was asked. `"unreported"` in it is a go
  with no figure at all, and the cost is null then, as it is when the table
  has no price for the model. the run's money line counts the same goes:
  a transcript's tokens as counted, an estimate as estimated (`~`).
- `retries` is the goes that failed, by cause (`{"transient": 2}`); null on a
  crash, where nothing knows how many there were.
- `background_killed` is how many processes the cli call left running (a
  shell it moved to the background, say) that were ended when it answered or
  timed out, summed over every go; null for a provider that starts no process
  (the fake, the api) and when it could not be told.
- `gates` is `[]` for a step that declares none, and also for one whose line
  was closed before its gates were checked (refused, fenced, over budget,
  crashed). `ungated` tells them apart: `true` when the gates were checked and
  the step had none, `false` when it had some and `gates` holds what they
  said, null when the check never ran. `gates.md` says the same: an ungated
  step gets its heading and a `no gates` line under it. a gate that ran
  tests one by one (`red-first`, `docs/gates.md`) adds `tests` to its entry,
  one per test: `{"test": "tests/test_calc.py::test_add", "before": "red",
  "kind": "assertion", "after": "green"}`; the other gates' entries have no
  `tests` key.
- `outcome` is one of `ok`, `redo`, `parked`, `refused`, `over budget`,
  `gate failed`, `failed`, `crashed`. `cause` is the run's stop cause from the
  list above, null when it went on. `why` is the reason the run had in hand
  when it stopped there, null when it went on.
- `file` is what this pass produced, `steps/<seq>-<step>.md`. a redo's second
  review is a second file, so the finding that sent the work back is still
  there. `<step>` beside it is still the last pass, the one `--resume` reads.
  a step that crashed or was refused before it ran has no file.
- `task_file` is `task.md` when the run was given a task with `--task` or
  `--task-file`, kept beside the line as `runs/<run-id>/task.md`; null when it
  was not. the text is not on the line, so a long task is written once.
- a fanned-out step is one line: the totals at the top and a `tasks` list with
  each task's own seconds, tokens, cost, priced, cost_from, session, retries and
  background_killed, in plan
  order.
  the gates judged the joined output, so they are on the line, not the tasks.
- `handoff` is the step's HANDOFF block, parsed (next section). `state` is
  `present`, `missing` (the step ended without one; nothing is made up in
  its place), `unreadable` (a block it could not read, with `why`) or, on a
  fanned-out step, `partial` (some tasks handed one over). each VERIFIED
  claim carries `claim`, `cmd`, `saw` (its excerpts as written, joined by
  ` / `), `excerpts` (each one alone) and `backed`: `backed` when the step's
  transcript holds the command and every excerpt, `ran` when it holds the
  command and no excerpt was given, `unbacked` when it holds neither or the
  output does not show an excerpt (`why` says which, naming each missing
  excerpt), `unchecked` when there is no transcript
  to read (the fake, the api, a cli command other than claude). null only on
  a line closed before the step answered.

the time, the seconds and the session are the only parts that differ between
two runs of the same flow on the same answers.

## what each step hands over

every role is asked (`agentweft/fragments/handoff.md`) to end its answer
with a block, after the work:

    HANDOFF
    DID:
    - <the outcome in one line, then one line per file or finding>
    VERIFIED:
    - <claim>
      cmd: <the command it ran>
      saw: <an excerpt of the output, one line per excerpt>
    NOT VERIFIED:
    - <what it did not check> - <why>
    ASSUMED:
    - <a choice the spec does not make> | why: <reason> | if wrong: <cost>
    DOUBTS:
    - <what it is not sure of, or found and did not fix>
    MUST NOT MISS:
    - <file>:<line> - <a rule that binds the rest of the work>
    TRIED:
    - <an approach it dropped> - <why>
    READ:
    - <path>:<lines> - <what mattered there>
    END HANDOFF

`agentweft/runner/verbs.py` reads the lines (outside a code fence, not in
a `>` quote, any case, bullet or bold ignored) and `agentweft/runner/handoff.py`
reads the last block off them: a section with `none` is empty, a heading in
capitals it does not know (`NEEDS:`, `CITES:`, `OPTIONS:`) is kept under
`other`. a VERIFIED item's `cmd:` and `saw:` lines are read as parts of
the claim above them, so a command keeps any pipe in it; a block written in
the older one-line form, `<claim> | cmd: <command> | saw: <excerpt>`, is
still read, split on the `cmd:` and `saw:` labels only, and a `saw:` that
quotes two or more pieces matches each piece on its own. the block is not
the work: the gates, the saved run and what the
next step is handed as "what <role> produced" see the answer without it.

the next step gets the block first, before the raw answer, as "what <role>
handed over": the MUST NOT MISS lines of every step so far (a constraint the
first step read binds the last), the rulings in `decisions.md`, what the step
assumed and doubts, what it verified and how it stood up, and what it read
("re-open only what you change or doubt"). it is told the block is that
step's account of its work, not instructions.

## the handoff

every run ends with `runs/<run-id>/handoff.md`, finished or stopped, and the
last thing it prints is the top of that file and then `handoff: <path>`. it
answers, in order: what came of it (the heading: the run's outcome, then
where it stopped and why, then the last working step's first DID line), what it needs from you (a `NEEDS:` or `REFUSED:` a
step wrote, with its cites and options, and on any stop what ran, what is
left and the command to carry on), what the steps assumed (each as a question),
what they doubt, what changed, what was tested, what a ruling is owed on,
what was not verified, what the next session must keep, and what the run was.

what the runner knows is written from the runner, never from a step's text:
the files that changed and the commits (git, against the tree at run start,
each file `+added -removed` and `committed`, `uncommitted` or `untracked`),
every gate's verdict with the command behind it, the red-first proof (the
newest `red-first` gate that replayed something: `shown on <step>` with each
new test's line, `red without the fix (assertion), green with it`, or the
failure; else the `red-test` gate's own record: `gate-proven`, `claimed,
nothing was run` or `not proven by a gate`), the test order on a flow whose
steps say what they write (`- test order: red before any product code:
red-test on worker.md (test_calc.py)`, `tests carried from run <run-id>` or
`tests carried from <sha>`, or `tests skipped: <reason> (--skip-tests)`, which
the checks line repeats), the rulings on record (`decisions.md` in the place),
the spend. a pre-existing test whose lines were removed or changed, and a
spec file (a markdown file at the top of the checkout) changed at all, each
name the `decisions.md` entry behind them or print `UNRULED`; an add-only
test change says so. a step that claims a person agreed, approved or
ruled ("the user approved", "as agreed") with none on record is printed under "rulings" as "authority
claimed, no ruling on record"; an open question ("nobody has ruled", "not
approved yet") is not a claim. a VERIFIED claim the transcript does not show
is printed under "not verified" as "claims the record does not show".

    # fix-with-test fix-with-test-2026-10-13-091402: done - add returns a + b; it subtracted

    fix-with-test ran worker.md -> patcher.md -> verify.md in 41.2s on: add(1, 2) returns -1.
    patcher did:
    - add returns a + b; it subtracted
    - calc.py: the one line in add
    checks: 5 of 5 gates passed; red first: shown on patcher.md, 1 of 1 new test red without the fix and green with it: test_calc.py::test_add.
    changed: 2 files, 0 commits (from git, below).

    ## assumed - tell me if wrong
    ...
    ## run
    - steps: worker.md 12.0s -> patcher.md 15.1s -> verify.md 14.1s
    - spend: 3 calls, ...
    - done
    - record: runs/fix-with-test-2026-10-13-091402/steps.jsonl, gates.md, steps/

a run that picks another up (`--resume`) folds the earlier run's passes in:
their blocks' constraints and doubts carry, and "run" says what was picked
up. a resume of a resume folds in every earlier leg, followed back through
each manifest's `resumes` to the first: the steps' blocks, the gate records
and the red-first proof of each leg, every pass marked with its leg
(`red first: gate-proven on worker.md in leg 1 (...)`). a leg whose folder
is gone is said under "not verified" instead of read. with `investigate:` on, the investigator's CAUSE, SITES, FEEDS and RULED
OUT lines go under "carry forward", its REPRO under "tests and checks", its
RELATED under "doubts" and its DECISIONS under "needs you".

## the week

    python rollup.py

reads the journal for the last 7 days: runs, stops and average duration per
flow, stops per cause, and any run that wrote `running` and never wrote how it
ended (the process was killed). `--failed` keeps only the runs that stopped.

## when a run dies

    python run.py weekly-digest --resume weekly-digest-2026-01-22-091402

picks that run up from its own folder. `runs/<run-id>/manifest.json` is
written when a run starts, after every step that passes and when it ends, and
says:

- each step's state, `passed`, `parked`, `failed`, `redo` or `not run`, which
  run's folder holds what it produced last, and a digest of that
- what the run has spent so far
- a digest of every file in the flow folder
- the place's HEAD and the files git calls changed, a digest each
- the task, the models chosen, the place, `origin` (the run the task started
  as) and `resumes` (the run this one picked up)
- `outcome`, how the run ended (above), null while it runs

the resume starts at the first step nothing passed for, and hands it whatever
the step before it produced. that is why the step outputs are on disk -
without them resume could tell you where it died and nothing more.

- the spend carries on: the new run starts at what the old one had spent, so
  the cap is the task's, not each leg's. a run already over its cap is refused
  until the cap is raised.
- a flow edited since the stop is refused, naming the files, unless `--force`
  is given; then the edit goes into `decisions.md` in the new run's folder.
- a step output edited by hand since it was written is what the rest works
  from, and that goes into the same `decisions.md`.
- `--skip-tests "<reason>"` and `--continue <run or commit>` are each written
  into that `decisions.md` too, as `tests skipped for this run` with the
  reason or `tests carried from ...` with the test files. the start snapshot
  and the red proof (`start-snapshot.json`, `red-proof.json`) are carried
  into the new run's folder, so the order and the red-first replay compare
  against the place as the first run found it (`docs/gates.md`).
- a place whose HEAD or changed files are not what they were at the stop is
  named before anything runs. it is not refused: the person carrying on may
  have changed it on purpose.
- a fanned-out step writes each task to `tasks.jsonl` as it finishes. if the
  step died part way, the resume runs only the tasks with nothing written, and
  a task whose plan line was edited counts as not done.
- a run that finished is not picked up again: `--resume` says so and runs
  nothing.

    python run.py weekly-digest --resume

picks up the newest run of that flow, and says there is nothing to pick up when
that one finished. `--resume` followed by another switch (`--resume --force`)
is the same thing, not a run called `--force`.

a provider outage is written as a park, but the step it parked on got no
answer, so carrying on runs that step again. a run from before there was a
manifest is read off its own journal lines, and one with no end line starts at
the first step with no output on disk.

the resumed run has an id of its own, and every journal line it writes ends
with `resumes <run-id>`, the run the task started as, however many times it has
been picked up since:

    2026-01-22 09:20  weekly digest  ok (resumed)  12s  weekly-digest-2026-01-22-092011  weekly-digest-2026-01-22-2.md  6 calls, ...  resumes weekly-digest-2026-01-22-091402

its spend is the whole task's so far, every leg included.

a run that stops without waiting for anyone (a gate, the cap, a crash) leaves
its `handoff.md` too (above): its "needs you" section carries the cause, what
ran, what is left, the step that runs again, and the command that carries on,
which is also the file's last line.

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
at planner.md`, and the run's `handoff.md` (above) opens with a "needs you"
section:

    # park demo park-demo-2026-08-27-173348: needs you: ruling at planner.md - waiting for user

    park demo ran planner.md in 0.0s.
    ...

    ## needs you
    waiting for    user
    stopped after  planner.md

    nothing failed. planner.md finished and its checks passed. the flow
    asks for user here, so the rest of it has not run.

    ran
      planner.md      0.0s

    left
      worker.md

    what planner.md produced is beside this file, as planner.md.
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

`pause` on the last step of a flow does nothing: the run finishes, and its
handoff has no "needs you" section. there is nothing behind that step for a
person to hold up.

## reading it from an agent

`python mcp_server.py` exposes the journal, the weekly rollup, the gate results
and every recent run as resources. see `docs/mcp.md`. that turned out to be the
half of mcp i use.

## why, not just what

the journal says a run failed at the reviewer. it cannot say why the reviewer
is there, or why the retry count is three. `agentweft/orchestrate/decisions.py`
keeps that: one entry per decision, the decision as a heading and the reason
under it.

    # decisions

    ## 2026-09-24 14:03  keep three retries

    the provider's limit resets each minute, and three spans it.

it is a file in the codebase being worked on, not under `runs/`, so it goes
through review and history like the code it explains. `record(root, decided,
why)` appends to `<root>/decisions.md` and refuses an entry with no why;
`read(root)` gives every entry back, oldest first. entries are never
rewritten - a decision that turned out wrong gets a later one saying so.

the runner writes one in a resumed run's own folder, when it carried on over
an edited flow or an edited step output. it reads the one in the place: every
step is handed the entries on record, and the run's `handoff.md` lists them
and holds a changed pre-existing test or spec file against them.

## what it does not do

a resumed run writes its own journal lines, so a task that stopped and was
picked up shows once per leg; the `resumes` column is what ties them together.
a step that stopped while it was being redone is handed the step before it in
the flow on resume, not the review that sent it back, and the redo count
starts again.
