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
no counts, no money` instead of adding up to nothing. `reported` there is only
what the providers said; a go priced from its transcript is added up as
`table-priced` and one estimated from its prompt as `estimated`, each beside
it (a step line written before `cost_parts` existed, with goes of more than one
kind, is `mixed, not split`).

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
(a park, a provider outage, a cap), `refused at <step>` when a step declined
the work citing the spec, `stopped at <step>` when a step found the request
contradicts the spec or the run's change could not be signed off against its
branch, and `failed at <step>` otherwise, and its cause is one of a fixed
list:

- `gate failed` - a gate failed the step, or the step did not give the router
  what the flow requires of it (an output it must contain, a verdict it can
  read). the why is the gate and what it said.
- `refused` - the step was not allowed to start (the place changed under it)
  or its output was refused (a preflight in `refuse` mode).
- `parked` - the flow asked for a person, a step asked for a ruling (below), a
  preflight parked, the work ran out of redos, or files git cannot give back
  were changed.
- `provider outage` - the account's own limit refused the call: a session,
  weekly or usage limit. the run parks after that one call, never retries and
  never hands the empty answer to a gate; the why and `handoff.md` say when
  the provider said it resets, or `unknown`.
- `budget` - the call or token cap. the run parks before the step that would
  cross the call cap, or once 80% of the token cap is spent; the why opens
  with `reached` or `reaching` and how far it got (`completion 2/3 steps`),
  and the step it parked before has not run (`docs/guardrails.md`).
- `exception` - something raised; the traceback is printed as well.
- `interrupt` - Ctrl-C.
- `no answer` - the step came back empty after its retries. the why carries
  the last thing the provider said.
- `declined` - a step answered `REFUSED:` with a spec line it cites (below).
  the run ends there, and that is its answer, so it exits 0.
- `conflict` - a step answered `CONFLICT:` with a spec line the request
  contradicts, and the quote was at that line as the run found it (below),
  or a test the run started with went red after a product step (below).
  nothing broke; the run waits for someone to say which one holds.
- `overlap` - a task of a fanned-out step wrote a file it did not name under
  `FILES:`, two tasks wrote the same file, or a file changed while two tasks
  ran side by side and one did not name it (`docs/flows.md`). the why names
  the files and the tasks.
- `target moved` - the branch the run's change is for moved while the run
  worked, and the change conflicts with its new head (`docs/guardrails.md`,
  the sign-off). the why names the files and the head to rebase onto.
- `merge unchecked` - the sign-off could not check the change against its
  branch with read-only git. the why says what to check by hand.

the same cause and why go on the step's line in `steps.jsonl` and into
`runs/<run-id>/why.md`. a cause off the list is refused where the line is
written, and `rollup.py` refuses one it finds.

`run.py` exits 0 when the run finished, was not due or a step declined with a
cite, 1 when it could not start, 2 when it stopped, and 130 on an interrupt.

what it prints is UTF-8 when piped to a file or a program, whatever the
locale, unless `PYTHONIOENCODING` says otherwise. on a terminal a character
the console has no byte for is printed as `?` rather than stopping the run.

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
| `declined` | `refused (spec cited)` |
| `conflict` | `stopped: spec conflict` |
| `overlap` | `stopped: tasks overlap` |
| `target moved` | `stopped: target moved` |
| `merge unchecked` | `stopped: merge unchecked` |
| `off task` | `stopped: off task` |

the map is `OUTCOME` in `agentweft/runner/stops.py`, with no default: a cause
with no outcome is refused where the outcome is read. a step that will not do
what it was asked because the spec says otherwise ends `stopped: spec
conflict` when it says so with a checked `CONFLICT:` line; one that only lets
a gate fail still reads `stopped: gate failed`. the exit codes do not change
with it.

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
or crashed. the keys are always all there, in this order, and `continued`
comes after them on the line of a step that carried its session on:

    {"seq": 1, "time": "2026-01-22T09:14:03", "step": "worker.md",
     "from": null, "to": "reviewer.md",
     "provider": "cli", "command": "claude", "model": "a-model",
     "model_reported": "a-model-1", "model_choice": null,
     "effort": {"asked": "provider default", "base": null, "raised": 0,
                "applies": true},
     "verbosity": null,
     "grant": null,
     "tokens": {"counted": true, "input": 12, "output": 4,
                "cache_read": 2, "cache_creation": 0},
     "cost": 0.25, "priced": 0.25, "cost_from": null, "cost_parts": null,
     "session": "s-1",
     "seconds": 8.4,
     "cached": false,
     "retries": {}, "background_killed": 0,
     "shell_writes_denied": null, "shell_trap_recoveries": null,
     "gates": [{"gate": "length", "ok": true,
                               "detail": "1 lines"}],
     "ungated": false,
     "outcome": "ok", "won": "none", "cause": null, "why": null,
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
- `effort` is how hard the step's model was asked to think: `asked` is the
  level sent, `"provider default"` when none was set anywhere and the
  provider's own default answered; `base` is the step's own level before any
  send-back, null for none; `raised` is how many times the step had been sent
  back when this go started (a gate, a verdict of redo, a wrong test), each
  one level up from the base to `xhigh` at most; `applies` is false when the
  provider cannot act on a level, as for `model_choice`. null on a line closed
  before the step was asked.
- `verbosity` is null for a step that is not terse. a `verbosity: terse` step
  has `{"asked": "terse", "limit": 8000, "applies": true}`: `limit` is the
  token cap its answer was held to, and `applies` is false, `limit` null, when
  the provider cannot hold an answer to one (the fake, a cli command other
  than claude), so the step got the terse words and no cap.
- `grant` is null for a step that declared no `tools`. otherwise it is the
  grant and what was done with it: `{"tools": ["read"], "enforced": true,
  "argv": [...], "cli_version": "2.1.296", "shell_writes": null}`.
  `shell_writes` is `refused` when a `shell` grant came with the shell-write
  check, `not enforced` when it did not, null without a `shell` grant. `argv` is the command line
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
- `continued` is only on the line of a step that carried its own session on
  (`continue: resume`, `writing-a-flow.md`): the id of the session it carried
  on. its `tokens` and `cost` are what the call added, not the whole
  session's, and `session` is the copy the call wrote.
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
  `cost_parts` is the same cost split by those kinds, in USD,
  `{"provider": 0.005, "estimate": 0.0008}`; null whenever `cost_from` or
  `cost` is.
- `retries` is the goes that failed, by cause (`{"transient": 2}`); null on a
  crash, where nothing knows how many there were.
- `background_killed` is how many processes the cli call left running (a
  shell it moved to the background, say) that were ended when it answered or
  timed out, summed over every go; null for a provider that starts no process
  (the fake, the api) and when it could not be told.
- `shell_writes_denied` is how many shell commands that write a file the cli
  refused this step (`providers.md`, a shell step writes files with the write
  tool), counted from `runs/<run-id>/tool-denials.jsonl` by the step's
  sessions; null for a step that was not handed the check, and when no
  session says which refusals were its own.
- `shell_trap_recoveries` is how many of the model's messages in the step's
  transcript name a shell trap it walked into: a `sed` that did not match, a
  heredoc that turned escapes into newlines, flipped CRLF line ends. null when
  there was no transcript to read. it counts what the model said, so it is a
  floor, not a census.
- `gates` is `[]` for a step that declares none, and also for one whose line
  was closed before its gates were checked (refused, fenced, parked at the
  cap, crashed). `ungated` tells them apart: `true` when the gates were checked and
  the step had none, `false` when it had some and `gates` holds what they
  said, null when the check never ran. `gates.md` says the same: an ungated
  step gets its heading and a `no gates` line under it. a gate that ran
  tests one by one (`red-first`, `docs/gates.md`) adds `tests` to its entry,
  one per test: `{"test": "tests/test_calc.py::test_add", "before": "red",
  "kind": "assertion", "after": "green"}`; the other gates' entries have no
  `tests` key. a test added after the red was first shown also carries
  `"added": "after green"` and `"counts": "coverage"` or `"pin"`, and an
  allowed pin `"pin_ok": "<role>: <reason>"`.
- each gate a step ran also has a line of its own in
  `runs/<run-id>/gates.jsonl`, with its seconds, which the step's `seconds`
  never hold:

      {"seq": 3, "step": "worker.md", "gate": "command", "ok": true,
       "seconds": 4.212}

  `seq` is the step's line. the check of the tests the run left red when it
  stops is a line too, `left-red`, with no `seq`.
- `outcome` is one of `ok`, `redo`, `parked`, `refused`, `gate failed`,
  `failed`, `crashed`, or for a question that went to the flow's lead,
  `asked` on the step that asked and `decided`, `overruled` (it answered
  `DECIDED:` and the runner did not hold it, `why` says what stopped it) or
  `escalated` on the lead's go; a line written before the cap was checked ahead of
  each step can say `over budget`. `cause` is the run's stop cause from the
  list above, null when it went on. `why` is the reason the run had in hand
  when it stopped there, null when it went on.
- `won` is what the pass bought, set by the runner from the line and the
  run's record, never from what a gate or the step wrote:
  - `caught`: a gate failed on its work, or its verdict sent the work back
    (a redo that only switched the cause step on is not one). a gate that
    could not run (a command not on PATH, a gate set up wrong, a replay that
    could not build its checkout) carries `"broke": true` on its entry and
    caught nothing.
  - `proved`: the run's red proof (`red-proof.json`) was written by this
    pass. a gate that passed is not enough, and a proof carried in with
    `--continue` names no pass.
  - `stopped`: it ended the run on a conflict, a refusal or a park for a
    ruling or a person (`cause` `conflict`, `refused`, `declined` or
    `parked`), with the place as it found it; a park for the budget or an
    outage, a crash and no answer bought nothing.
  - `delivered`: the same stop, with its work in the place: the place's
    content (in git, the commit and every file that differs from it) is not
    what it was before the step ran. a pass that went on (`ok`) is
    `delivered` too when its work is in the place and a gate that ran
    passed it: one not `skipped` and not `broke`, so a program checked the
    work.
  - `decided`: the lead's go whose decision is on record in `decisions.md`;
    the pass that asked is `none`, it runs again.
  - `none`: anything else, an all-pass judge among them.
  the retro in `handoff.md` sums seconds and money by it.
- a flow with `retro: true` can end on one more line, step `retro.md`,
  written after the handoff: `outcome` `ok` or `failed` with its why, never
  a cause, `won` `none`, `budget` null (`writing-a-flow.md`). what it wrote
  is `runs/<run-id>/retro.md`.
- `file` is what this pass produced, `steps/<seq>-<step>.md`. a redo's second
  review is a second file, so the finding that sent the work back is still
  there. `<step>` beside it is still the last pass, the one `--resume` reads.
  a step that crashed or was refused before it ran has no file.
- `task_file` is `task.md` when the run was given a task with `--task` or
  `--task-file`, kept beside the line as `runs/<run-id>/task.md`; null when it
  was not. the text is not on the line, so a long task is written once.
- a fanned-out step is one line: the totals at the top and a `tasks` list with
  each task's own seconds, tokens, cost, priced, cost_from, cost_parts, session,
  retries and
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
- `chain` comes last: `{"prev": "<sha256>", "files": {"start-snapshot.json":
  "<sha256>", "red-proof.json": null}}`. `prev` is the sha256 of the line
  before it as it stands in the file, null on the first line; `files` is the
  sha256 of the run's start snapshot and red proof as the runner last wrote
  them, null for one the run did not write. it is never read off what a step
  left on disk.

the time, the seconds and the session are the only parts that differ between
two runs of the same flow on the same answers, and the chain's hashes, which
take in the time.

### the chain

the start snapshot and the red proof hold the hashes the test files are held
to, and a step that may rewrite a test may as well rewrite those. so each
line hashes the one before it and those two files, the manifest keeps the
line count and the head (the newest line's hash) each time the handoff is
written, and the handoff names the head. a line edited, dropped or put out of
order after it was written then shows:

    python run.py verify fix-with-test-2026-10-13-091402
    fix-with-test-2026-10-13-091402: broken: line 3 (seq 3, verify.md) was edited after it was written

it names the first line that breaks: an edited line (a gate's `"ok": false`
turned to true), the seq of a dropped one, a line out of order, a last line
dropped or edited (against the manifest's head), or a start snapshot or red
proof that is not what the runner last wrote. that takes in a rewrite made
during a step: the step's own line carries the hash the runner wrote, not the
one the step left, so the step that rewrites a test and the hash it is held
to is named too. exit 0 when it holds, 1 when it breaks or
the record was written before lines were chained.

`--resume` checks the same before it picks a run up, and refuses one that
breaks with what broke; `--force` carries it on anyway and writes the break to
`decisions.md`.

it has no key. a writer who rewrites a line and every hash after it, the
manifest's head and the handoff's line with them, is not caught: it catches
an edit, a drop or a reorder, not a determined forger.

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
    - <a choice the spec does not make>
      why: <reason>
      if wrong: <cost>
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
quotes two or more pieces matches each piece on its own. a `cmd:` that
points at the command above it (`(same command as above)`, `(same
command)`) is read as the nearest command above it in the section and
matched as that; one cut short with `...` is marked `shortened` rather than
`unbacked`, printed under "not verified" as "shortened, so not held to the
record", and the prompt asks for every command in full. an ASSUMED item's
`why:` and `if wrong:` lines are read the same way, as parts of the choice
above them; the older `<choice> | why: <reason> | if wrong: <cost>` line is
still read. the handoff prints each assumption on one line with its labels.
the block is not
the work: the gates, the saved run and what the
next step is handed as "what <role> produced" see the answer without it.

the next step gets the block first, before the raw answer, as "what <role>
handed over": the MUST NOT MISS lines of every step so far (a constraint the
first step read binds the last), each line once with the roles that kept
it, the rulings in `decisions.md`, what the step assumed and doubts, what it
verified and how it stood up, and what it read ("re-open only what you
change or doubt"). it is told the block is that step's account of its work,
not instructions.

## the handoff

every run ends with `runs/<run-id>/handoff.md`, finished or stopped, and the
last thing it prints is the top of that file, its "needs you" section, and
then `handoff: <path>`. sections are separated by blank lines and `## `
headings, never by `|`.

the top is the default view, held to about 900 tokens (four characters to a
token); a list that does not fit is cut to a line ending `more in the full
record below`, and when that is not enough the heading and the lines under it
are cut to width too (a long task line or stop reason is in full below). it
answers, in order:

- **what came of it**: the heading, the run's outcome, then on a stop where
  and why; only a run that got through adds the last working step's first
  DID line, so a stop never leads with "fixed". then what ran, the `suite:`
  line (gates passed, the checks the runner made outside the gates and the
  red-first proof) and the `changed:` line. a conflict stop counts its
  quote check (`1 check passed (the quote at TASK.md:3 is there as the run
  found it)`), or the tests the run started with run again; `no gates ran`
  is only for a run that checked nothing.
- **the one decision**: the open questions, from a `QUESTION:` line in a
  step's HANDOFF block (which never stops the run), a `NEEDS:` or
  `CONFLICT:` line (which do), a doubt that is a question, what the
  investigator leaves to you, and a spec or test change nobody ruled on. two
  are one when they cite the same spec line (`TASK.md:12`) or say the same
  thing once case, punctuation and the cited line are taken out; the same
  words about two different spec lines stay two. each is
  printed once, with every role that raised it, and the recommendation and
  its size the first of them gave (`RECOMMEND:` and `SIZE:`, each on its own
  line under the `QUESTION:` or `NEEDS:`; a doubt from an older block that
  carries them after a pipe is still read); the
  first is in full, the rest one line each under
  `also open:`. a question the lead decided or an `--answer` settled is under
  the rulings, not here, so a finished run needs nothing. `- none: nothing
  waits on you.` when nothing does; a `QUESTION: none` asks nothing, and the
  `RECOMMEND:` and `SIZE:` under it go with it. a stop that waits for a
  ruling leads with the question it wrote to `question.md`, with its cites
  and options, whatever asked it: a `NEEDS:` or `CONFLICT:` line, `VERDICT:
  park`, a `REFUSED:` with no spec line cited, a spec change request, or the
  runner. a stop that asked nothing (a gate, the cap, an outage, a crash, a
  refusal that cites the spec) leads with the stop itself, where and why,
  and the questions the steps left open follow it under `also open:`.
- **why**: what the last working step did (on a stop, "handed over this
  before the stop, not taken as done"), and what the steps assumed.
- **not done**: what was not verified, the gates' unproven checks, and the
  doubts left as they are, each once: by its words, or by the spec line it
  cites, with the roles that raised it, and how many times when one role
  raised it again after a send-back, so a doubt that was not fixed says so.
- **product gaps**: each spec line an open question turns on, and each spec
  file the run changed.

then `## full record`, which names `runs/<run-id>/steps/` and
`steps.jsonl`, and every section in the runner's order: what it needs from
you (a `NEEDS:` or `REFUSED:` a step wrote, with its cites and options, and on
any stop what ran, what is left and the command to carry on), what the steps
assumed (each as a question), the open questions the default view does not
print in full (`## open questions`, when there are any: each wording once
with the roles that asked it, so a question joined to another by its spec
line, cut to its width or past the cut is still on record), what they doubt
that is not a question (each once by its words), what changed, what was
read, what was tested, what a ruling is owed on, what was not verified, what
the next session must keep (each line once, with the roles that kept it),
what went wrong on the way, and what the run was.
the whole file looks like the example at the end of this section.

what the runner knows is written from the runner, never from a step's text:
the files that changed and the commits (git, against the tree at run start,
each file `+added -removed` and `committed`, `uncommitted` or `untracked`),
every gate's verdict with the command behind it, each check the runner made
outside the gates (`- <step>: PASS quote check - <what it found>`), the
red-first proof (the
newest `red-first` gate that replayed something: `shown on <step>` with each
new test's line, `red without the fix (assertion), green with it`, a case
added after green ending `; added after green, coverage` or `; added after
green, pins current behaviour, not counted as coverage`, or the failure; else the `red-test` gate's own record: `gate-proven`, `claimed,
nothing was run` or `not proven by a gate`, and on a flow whose steps say
what they write and whose red-proof record holds no proof, `not held: the
red-test gate on <step> went red (...), but the run holds no red proof`
rather than `gate-proven`), the test order on a flow whose
steps say what they write (`- test order: red before any product code:
red-test on worker.md (test_calc.py)`, `tests carried from run <run-id>` or
`tests carried from <sha>`, or `tests skipped: <reason> (--skip tests)`, which
the suite line repeats), each gate skipped by name with its reason (`- regex
skipped: <reason> (--skip)`, also on the suite line), the rulings on record
(the entries of `decisions.md` in the place that the runner wrote or found
there when the run started),
the spend. a pre-existing test whose lines were removed or changed, and a
spec file (`TASK.md` or `SPEC*.md` at the top of the place, or a file under
`docs/spec*` there; a `*` never crosses a `/`) changed at all, each
name the `decisions.md` entry behind them or print `UNRULED`; an add-only
test change says so, and so does a spec file with lines added and none
removed in a flow with `spec_files: additions`, which allows exactly that:
it is not owed a ruling and is not in the one decision. a step that claims a person agreed, approved or
ruled ("the user approved", "as agreed") with none on record is printed under "rulings" as "authority
claimed, no ruling on record"; an open question ("nobody has ruled", "not
approved yet") is not a claim. a VERIFIED claim the transcript does not show
is printed under "not verified" as "claims the record does not show".

five sections are written by the runner alone:

- **changed**: each file with `+added -removed`, how it stands, and the lines
  the change covers (from `git diff --unified=0`; an untracked file is all of
  its lines), then what `git status --short` and `git log --oneline
  <start>..HEAD` print, line for line. "nothing is committed" is a claim about
  a moment; the two commands' output, taken when the handoff is written, is
  the record.
- **read**: per pass, the files and ranges its session's transcript shows it
  read (a Read call by offset and limit, a `cat`, `head`, `tail` or `sed -n`
  target in a shell call), with the step's own READ lines under it as `said:`;
  a READ line its transcript does not show is `said, not in its transcript:`.
  a pass with no transcript says so.
- **tests and checks**: each new test's red-first record, ending `- encodes
  TASK.md:12 (patcher)` when a step's line names the test and a spec line.
- **see the fix by hand**: on a run that finished holding a red proof shown
  by a gate in it, the command for each test the red-first replay showed
  red without the fix and green with it, without the results file the gate
  reads and with the id quoted for the shell it runs in (or, with no
  replay, the command the red-test gate ran red), then the commit the run
  started at,
  where the same command with the proved test files fails. it is read from
  the red proof and the gate record, never from a step; a run with no proof,
  or one that stopped, has no such section.
- **retro**: per pass, its seconds and cost, its outcome when it was not ok,
  each gate it failed, its retries (`limit events`, `refused calls`,
  `retried after transient`), refused shell writes, shell-trap recoveries and
  leftover processes ended, all from `steps.jsonl`, and what it won (`won`
  on the step line); then one line per send-back with the reviewer's reason;
  then the money and seconds summed by what each pass won, `won none` always
  among them, and the total, which is the sum of the steps. a pass whose cost
  was not stated is counted and named, never added in as nothing. last, the
  run's wall beside its steps, its gates and the runner: `- wall 41.0s:
  steps 29.3s, gates 9.2s, runner 2.5s`. a step's seconds are its model's
  time; a gate's are in `gates.jsonl`; the runner's are the rest (snapshots,
  commits, the end-of-run checks that are not gates), so the three add up to
  the wall of this run, not of the runs it picked up. fanned tasks that ran
  at once can sum past the wall; the line then says the steps are summed and
  leaves the runner out.

    ## changed
    - calc.py +1 -1 (committed), lines 2
    - notes.md +1 -1 (uncommitted), lines 3
    - git status --short:
         M notes.md
    - git log --oneline 44b0532..HEAD:
        47b60ab fix add

    ## read
    - worker.md read: calc.py:1-2; TASK.md:1-3
      said: calc.py:1-2 - add subtracts
      said, not in its transcript: docs/old.md:1-9 - the old notes

    ## retro
    - worker.md 12.0s ($0.2500), won none: no events
    - reviewer.md 4.1s ($0.2500), won caught: sent back
    - worker.md 9.3s ($0.2500), won none: no events
    - reviewer.md 3.9s ($0.2500), won none: no events
    - reviewer.md sent the work back: notes.md still says three
    - won caught: 1 pass, 4.1s, $0.2500
    - won none: 3 passes, 25.2s, $0.7500
    - total: 4 passes, 29.3s, $1.0000
    - wall 41.0s: steps 29.3s, gates 9.2s, runner 2.5s

    # fix-with-test fix-with-test-2026-10-13-091402: done - add returns a + b; it subtracted

    fix-with-test ran worker.md -> patcher.md in 27.1s on: add(1, 2) returns -1.
    suite: 4 of 4 gates passed; red first: shown on patcher.md, 1 of 1 new test red without the fix and green with it: test_calc.py::test_add.
    changed: 2 files, 0 commits (from git, below).

    ## the one decision
    - Should add(None, 1) raise, or count None as zero (TASK.md:4)?
      raised by worker, reviewer, 3 times; cites TASK.md:4
      recommendation: raise TypeError, as sub does (size: one line in calc.py)

    ## why
    patcher did:
    - add returns a + b; it subtracted
    - calc.py: the one line in add

    ## not done
    doubts, left as they are:
    - nothing else calls add, so no caller was checked (patcher)

    ## product gaps
    - TASK.md:4 - the one decision turns on it

    ## full record
    every line the run left, section by section; ...

    ## assumed - tell me if wrong
    ...
    ## run
    - steps: worker.md 12.0s -> patcher.md 15.1s
    - spend: 2 calls, ...
    - done
    - record: runs/fix-with-test-2026-10-13-091402/steps.jsonl, gates.jsonl, gates.md, steps/
    - chain: 2 lines, head 3f1c9a07be52d4e8 (python run.py verify fix-with-test-2026-10-13-091402)

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

- each step's state, `passed`, `parked`, `parked for a ruling`, `failed`,
  `redo` or `not run`, which
  run's folder holds what it produced last, and a digest of that
- what the run has spent so far
- how many times each step has been sent back, under `raised`, which a
  resume carries on counting from
- a digest of every file in the flow folder
- the place's HEAD and the files git calls changed, a digest each
- the task, the models chosen, the place, `origin` (the run the task started
  as) and `resumes` (the run this one picked up)
- `outcome`, how the run ended (above), null while it runs

the resume starts at the first step nothing passed for, and hands it whatever
the step before it produced. that is why the step outputs are on disk -
without them resume could tell you where it died and nothing more.

- the spend carries on: the new run starts at what the old one had spent, so
  the cap is the task's, not each leg's. a run still at its cap is refused
  until the cap is raised, with `--max-calls <n>` / `--max-tokens <n>` on the
  resume or in `flow.yaml`; a cap given on the command line stays in force on
  every leg until a higher one is given. the change goes into `decisions.md`
  in the place, and the run carries on at the step it paused before.
- a flow edited since the stop is refused, naming the files, unless `--force`
  is given; then the edit goes into `decisions.md` in the new run's folder.
- a step output edited by hand since it was written is what the rest works
  from, and that goes into the same `decisions.md`.
- `--skip <gate> "<reason>"`, `--skip-tests "<reason>"` and `--continue <run
  or commit>` are each written into that `decisions.md` too, as `<gate>
  skipped for this run` or `tests skipped for this run` with the reason, or
  `tests carried from ...` with the test files. the start snapshot, the red
  proof and the skips (`start-snapshot.json`, `red-proof.json`,
  `skips.json`) are carried
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

## when a step asks for a ruling

a step that cannot do its work without someone deciding something answers
with a question on a line of its own, with what it cites and the options it
sees under it:

    NEEDS: keep amounts as strings, or make them numbers?
    CITES:
    - TASK.md:158 - the JSON amount is a string with 2 decimals
    OPTIONS:
    - A: keep the spec
    - B: change it

(`VERDICT: park` as the first line does the same, with the next line as the
question.) the run parks there, before that step's gates run: a step that
stopped to ask has produced nothing to gate. a step that changed the place
before it asked did produce something, so its gates run on that first, and
the "needs you" section says it did the work, then asked, and whether those
gates passed or which one failed. the run parks either way. the journal
says `parked at <step>`, `why.md` says `kind       ruling`, the step is
`parked for a ruling` in the manifest, the question is in
`runs/<run-id>/question.md`, and the handoff's "needs you" section shows it
and ends with the command that answers it:

    python run.py fix-with-test --resume <run-id> --answer "numbers"

`--answer-file <path>` takes a longer answer from a file. the resume runs the
step that asked again, AT that step and not after it, on what it was handed
before, with the question and the answer at the very end of its prompt. the
question, the answer and who gave it go into `decisions.md` in the place the
run works in, so the ruling sits beside the code it changes and the handoff
lists it as on record. the runner also keeps its own record of every entry
it writes, with a sha256 and who wrote it (`answer`, `lead`, `cap`), as
`runs/<run-id>/rulings.json`; an entry in `decisions.md` that is neither in
it nor there when the run started rules nothing, and a step that changes the
file fails as a `rulings` gate with the file put back ("the rulings only the
runner writes" in `guardrails.md`). `--resume` on that run without an answer runs nothing:
it prints the question and the command, and exits 2. an `--answer` to a run
that asked nothing is refused.

a question can say what the step would pick and what that costs, each on a
line of its own under it:

    RECOMMEND: the date error first, the way parse() checks it now
    SIZE: zero code lines

a question whose recommended answer changes no code is the step's call, not
a stop. the runner prices the answer the `RECOMMEND:` picks, not the other
one: a `SIZE:` that prices each answer on its own (`none if left; one line
in importer.py if a lone CR counts`) is read on the answer whose words are
nearest the recommendation, the first one when none is nearer; a
recommendation to leave things as they are (`leave it`, `keep it as it is`)
costs nothing whatever the other answer would. when the recommended answer
changes no code (zero, none, no code, or one test and nothing else, each
part of the SIZE read on its own) the runner takes the question out of the
answer and puts it in the block as a doubt, `<question> assumed:
<recommend> (size: <size>)`. the step is taken as done and goes on through
its gates, and the handoff lists the doubt; the answer as the step gave it,
question and all, is kept beside its step file as `<step>.asked.md`. a
recommended answer that counts lines of code, no `RECOMMEND:`, or a `CITES:`
line (a gap in the spec, which a person rules on) parks as above; so does a
stop question whose only `RECOMMEND:` and `SIZE:` belong to a `QUESTION:` in
the block. the order two errors are reported in,
when the spec fixes neither, is the usual case: the step follows the code's
own convention and says so under ASSUMED.

the line is read the way every labelled line is (`agentweft/runner/verbs.py`):
its key in any case, behind a bullet or in bold; never inside a code fence or
a `>` quote, so a test that asserts on the string "NEEDS:" asks nothing.

a flow with a lead (`lead: <step>` in `flow.yaml`; build-feature's is the
planner) asks its lead before it asks you. a question from any other step
goes to the lead with the question, its CITES and its OPTIONS at the very end
of the lead's prompt, and the lead answers on lines of its own:

    DECIDED: numbers
    why: TASK.md:158 is about the JSON, and the code works in numbers

the decision goes into `decisions.md` as the lead's (`planner.md decided for
worker.md: numbers`, with the question and the why under it), and the step
that asked runs again with it at the very end of its prompt. in
`steps.jsonl` the asking step's line is `asked` with `to` naming the lead,
and the lead's go is a line of its own, `decided`. the run parks for you
instead when the lead answers `ESCALATE: <why>` or neither line (its go
`escalated`), or answers `DECIDED:` with no `why:` line or after changing
`decisions.md` itself (its go `overruled`, with why on the line). a
decision is judged by what the step acting
on it changes, not by the files it names: one that cites `TASK.md:3` or a
test and changes nothing stands. a lead decides inside the spec and the
tests, never over them, so its entry never counts as the ruling that lets a
spec line or a start test change: when the step acting on it rewrites or
removes a spec line, edits a test the run started with (even one the
decision names), or turns a test green at the start red, the run stops
there for you, the way it would with no decision. a question gets one round
with the lead, so
the same `NEEDS:` asked again after the lead decided it parks too. the
question in `question.md` then says why the lead did not decide it. a flow
with `lead: none` or no `lead:` (fix-with-test), and a question the lead
itself asks, park at once. a spec conflict never goes to the lead: which of
the request and the spec holds is yours.

a step can also decline:

    REFUSED: TASK.md:12 "a refund is income"

when the cited file is in the place and has that line, the run ends `refused
at <step>`, outcome `refused (spec cited)`, exit 0: the step's answer is that
the spec says no, and nothing is owed. the steps after it do not run. a
refusal that cites nothing, or a line that is not there, is read as a question
and parks for a ruling instead. the runner refusing to START a step is a
different thing, the `refused` cause, and that is a stop.

a step can say a test it was given is wrong, on lines of its own:

    WRONG TEST: tests/test_calc.py::test_mul
    why: 2 times 3 is 6, and the test wants 5
    spec: TASK.md:3 "mul(a, b) returns a times b"

a test that was not in the place when the run started (the start snapshot) is
the run's own: it goes back to the step that wrote it, with the claim at the
very end of its prompt, and that step's gates have to show it red again before
the work walks on, on the start commit when the step that made the claim
had already written code (`docs/gates.md`, red-test); the step's line in `steps.jsonl` is a `redo` with `to`
naming the writer. it goes back `send_backs` times per test, once by default,
and a second claim on the same test parks for a ruling. a test the run started
with never goes back: the claim parks for a ruling, quoted in `question.md`. a
`spec:` line that is not there is read as a question too.

the runner asks one of its own when a step in a flow with `spec_files:
additions` removes or rewrites a line of the spec the run started with
(`docs/guardrails.md`, "the spec files"). the run parks after that step's
gates, cause `parked`, outcome `needs you: ruling`, `gates.md` has a failed
`spec-files` line, and `question.md` quotes each line as it was and as it is
now (`TASK.md:3 - was "...", now "..."` or `now removed`). `--answer
"override: <why the change holds>"` lets those lines change, and the step runs
again to read the ruling; any other answer is told to the step, which has to
put the lines back or park again. in a `read-only` flow the same edit is a
failed gate instead: the step goes again once, then the run stops `gate
failed`.

## when the request contradicts the spec

a step that finds the request asks for what a line of the spec rules out
answers two lines, each on its own:

    CONFLICT: TASK.md:3 "the report lists students alphabetically"
    request: list them in roster order

a request that adds to the spec is not one. an option, flag, field or command
that leaves what a line requires true whenever it is not used extends that
line: with `- Fields are separated by commas.` in TASK.md, `--delimiter ;`
used only when given adds to it, and making the comma a semicolon contradicts
it. a conflict asks, for the same inputs and options a line already covers,
for something other than what the line requires. a line that forbids or
requires something in every case, with `never`, `always`, `only` or `must`,
already covers every option: with `- An amount is never 0.`, an
`--allow-zero` option that accepts 0 when given contradicts it, though the
line still holds whenever the option is not used. the build-feature planner
marks each behaviour `spec: allows`, `spec: adds to`, `spec: nothing in the
spec` or `spec: contradicts` with the line, and only a `contradicts` may end
the plan with a CONFLICT line. the flow takes additions to its spec files
(`spec_files: additions`), so the line for the new option can be written in,
as a new line: the steps are told to add under the line an option extends and
never to rewrite it, since a rewritten line waits for a ruling even when it
still says what it said.
the runner reads one mark: an answer that marks a behaviour `spec:
contradicts` and has no CONFLICT line fails the step like a gate (`conflict`
in `gates.md`), naming the marked lines, and the step goes again once with
that at the end of its prompt, to type the contradiction as a CONFLICT line
or mark the behaviour another way. a second such answer stops the run on the
gate. a marked line an earlier step's answer already holds is that step's,
so a later step that quotes it, the plan line as it was handed on, is not
sent back for it; a line it marks itself is. which mark a behaviour gets is
the prompts' rule; the runner stops on a
CONFLICT line whose quote is there, whoever wrote it.

the `request:` line counts only straight after the CONFLICT line. the older
one-line form, `| <the request's words>` after the quote, is still read. the cite may be a range (`TASK.md:51-53`), and the quote is read as one line
across it, with runs of spaces counted as one. the runner checks the quote is
at that line as the run found it: from the start snapshot, so `git show
<start>:<file>` or the bytes of a file that was already loose, never the file
as a step left it. a step cannot make its own cite true by editing the spec
first.

when the quote is there, the run stops before that step's gates: the journal
says `stopped at <step>` with cause `conflict`, the outcome is `stopped: spec
conflict`, exit 2, and the question is in `question.md` and in the handoff's
"needs you" section with the two commands that answer it:

    python run.py build-feature --resume <run-id> --answer "override: <the new rule>"
    python run.py build-feature --resume <run-id> --answer "request: <what to do instead>"

- `override:` lets the request win. the step that stopped runs again, with
  the answer at the end of its prompt and the line `this authorises changing
  TASK.md:3, and nothing else`.
- `request:` keeps the spec. the words are added under the request, which
  stays word for word above them, and the run starts again from its first
  step that is handed the request: in fix-with-test a conflict at the patcher
  goes back to the worker, because the test was written against the request
  as it was.

either goes into `decisions.md` with the question. an answer that starts with
neither word is refused for a conflict, since it would not say which one
holds.

a quote that is not at the line, a cite of a file that was not there when the
run started, or a line that is not `<file>:<line> "<quote>"` fails the step
the way a gate does (`conflict` in `gates.md`): it goes again once with what
was wrong, then the run stops `gate failed`.

the same stop comes from the runner when a step that writes product code
turns red a test that was green when the run started, run as the start commit
has it (`docs/gates.md`). the why names the test and its assertion:

    spec conflict: tests/test_report.py::test_alphabetical was green when the run started and is red now: AssertionError: assert ['b', 'a'] == ['a', 'b']

`gates.md` has it as a failed `start-tests` line, and the question lists each
such test. `override:` lets the change stand only if it names each test or
quotes the spec line that decides it: the step runs again, and its replay
reads the ruling. `request:` keeps the tests, as above.

## the tests a stop leaves red

a stop can be right and still leave a test failing in the tree: the worker
appended a red test to a supplied file, then the patcher stopped on a
conflict. git only says the file changed. so on every stop, whatever the
cause, the runner runs the tests the run added or changed since it started
(the start snapshot) once each, with the flow's first one-test command, in a
fresh python and with no model asked. each that is not green is named, in the
handoff's "needs you" section and so on the console, and the `changed:` line
counts them:

    changed: 1 file, 0 commits (from git, below); 1 test the run added or changed is red.
    ...
    left red when the run stopped (run once after the stop):
    - tests/test_export.py::test_amount_is_a_number: red (assertion)
    nothing was reverted; --on-stop revert-tests puts the test files back to their bytes at the start.

nothing is reverted by default: the red test is often the most useful thing
the run made. `on_stop: revert-tests` in flow.yaml, or `--on-stop
revert-tests` for one run (over the flow's), writes each test file the run
changed back to its bytes at the start and deletes each one it added, after
the tests ran, and the handoff names the files. a file whose start bytes the
snapshot cannot give back (outside git) is left and named. outside git, or in
a repo with no commit, there is no start to tell a changed test from its
neighbours, so every test in a changed file is run. a stop that changed no
test, or whose new tests all pass, says nothing about it.

## the run's own commits

a run commits nothing unless its flow says `commits: wip` or `commits:
squash` (`docs/writing-a-flow.md`). with one of those it starts on a branch
of its own, `agentweft/<run id>`, and after each step that changed a file it
commits what that step changed as `wip(<flow>): <step>`.
`runs/<id>/commits.json` keeps the branch, the commit it started from, the
branch it was started on and each step's commit with its files. `squash`
folds the step commits into one once every step has passed, its subject the
flow and the task's first line, its body the step commits it replaced,
its tree the last step commit's, renames and deletions included; your files
and your index are left as they are. a run
that stops keeps its step commits, and `--resume` carries on on the same
branch and squashes at its end; a resume with the place on another branch
refuses and names the run's. so does a step commit when the place has
left the run's branch mid-run, and a squash then is skipped, the handoff
naming the branch the place was on (or what git said, when it could not
squash): your branch is never committed on or
reset.

the handoff's tests and checks get one more line:

    - commits: wip on agentweft/build-2026-01-22-091402: tester.md 3f1c0a9e2b7d, worker.md 9a0e44c1d5b2, started from main; tests in 3f1c0a9e2b7d before the first product code in 9a0e44c1d5b2

the second half is the order as the commits show it: the first commit that
holds one of the red proof's test files, and the first that holds product
code. it is evidence beside the gates and no gate reads it, so a run gives
the same verdict whether it commits or not.

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
an edited flow or an edited step output, and one in the place for every
`--answer` to a step's question (above). it reads the one in the place: every
step is handed the entries on record, and the run's `handoff.md` lists them
and holds a changed pre-existing test or spec file against them.

## what it does not do

a resumed run writes its own journal lines, so a task that stopped and was
picked up shows once per leg; the `resumes` column is what ties them together.
a step that stopped while it was being redone is handed the step before it in
the flow on resume, not the review that sent it back, and the redo count
starts again.
