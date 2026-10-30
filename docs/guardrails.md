# guardrails

five things stop a flow doing something stupid. none of them are prompts,
which is the point - a prompt asking nicely is not a control.

a fifth one does not stop anything and says so on the tin. it is last, and
the reason it is in here at all is at the bottom.

## the spend cap

    max_calls: 20
    max_tokens: 120000

checked before every step. near it the run pauses rather than stopping: it
parks before the step, writes `parked at <step>` with the cause `budget` to
the journal, keeps what it has, leaves a `handoff.md` and exits 2 as any stop
does. its outcome is `needs you: budget`, and the why says how far it got:

    reached, completion 2/3 steps, call cap: 2 of 2 calls spent, and the next step takes 1
    reaching, completion 1/3 steps, token cap: 10750 of 12000 spent, 89% (~10750 estimated)

the call cap is read before the calls are made: a step that would take the run
past it does not start, and a fanned-out step counts one call per task it has
left, so `max_calls: 20` spends 20, never 21 or 20 plus a fan-out's width.
tokens are only known once a step has answered, so the token cap pauses at
`reaching` once 80% of it is spent and at `reached` once all of it is. the
call cap gets no 80% pause: it is counted exactly, so it never goes over.

the cap is for the task, not for one go at it: a resumed run starts at what
the run it picks up had spent, and one still at its cap is refused, so a budget
park carries on only once the cap is raised. raise it for that resume with
`--max-calls <n>` or `--max-tokens <n>`, or in `flow.yaml` (which edits the
flow, so the resume then needs `--force`). the handoff ends on that command,
with `<n>` where the new cap goes:

    python run.py weekly-digest --resume <run-id> --max-calls 30

a cap given on the command line is the run's, kept in its manifest and in the
manifest of every leg after it: a resume that does not name it carries on under
it, a resume of that resume too, every carry-on command the run
prints repeats it, and only a higher one on the command line gets past it.

the resume starts at the step the run paused before, and writes the change
into `decisions.md` in the place the run works in, beside the `--answer`
rulings, so the resumed run's handoff shows it: `carried <run-id> on with the
call cap from 20 to 30`, under the why the run paused with. a flow that says nothing gets the
defaults in `runner/settings.py`: 25 calls and no token cap. the call cap is
the one that catches a run going round in a loop, so it is on until a flow
sets its own.

the cap is read between steps, so it does not reach inside one: a `claude -p`
step's own turns are not counted until the step answers, and one step can go
past a token cap on its own. the next step is the one that waits.

every go at a model is charged, the failed ones a retry went through too. a
provider that reports usage (see `providers.md`) is charged exactly what it
reported, kept split the way it reported it, under the OpenTelemetry GenAI
names: `input`, `output`, `cache_read`, `cache_creation`, `reasoning`. `input`
already includes `cache_read` and `cache_creation`, and `output` already includes
`reasoning`, so the run's total is input plus output and nothing is counted
twice. a provider that reports nothing - fake, a command other than `claude` -
is charged characters over four, a guess meant only to say when a run is ten
times bigger than usual. a failed go with no usage is charged as a call and 0
tokens, tagged with the kind of failure; one the provider counted at 0 tokens
is a refusal, not a call (below). a cached answer is not charged, and
the cache is the run's own: a redo inside a run gets the answer it already
paid for, a second run or a second eval case asks again.

the two are never added into one number without saying so. the journal line
of a run that finished or stopped carries one of these, with its money after
the tokens (see the next section):

    3 calls, 360 tokens counted (input 300, output 60) (cli x3)
    1 call, 12850 tokens counted (input 12810 incl. cache_read 12000 and cache_creation 800, output 40 incl. reasoning 25) (cli x1)
    3 calls, ~1591 tokens estimated (fake x3)
    3 calls, mixed: 2 estimated calls, 120 tokens counted (input 100, output 20) + ~30 estimated (cli x1, fake x2)
    3 calls, 55 tokens counted (input 50, output 5), 2 failed calls charged 0 (transient x2) (cli x3)

`max_tokens` reads that total without the cache reads: input, cache writes and
output, plus any estimate. a cache read is a prompt the provider already had,
billed at a tenth of an input token or less in the shipped table, and on a
`claude` run it is often most of the count and little of the money, so a cap
that counted it stopped runs that cost cents. when it trips, the reason names the parts, and the cache reads it
left out:

    token cap: 851 > 850 (851 counted: input 10, cache_creation 800, output 41; cache_read 12000 not counted)
    token cap: 105 > 100 (90 counted: input 90, output 0, + ~15 estimated)

`max_calls` counts every go, failed ones included, except a go the provider
turned away and counted at 0 tokens, such as the account's usage limit. that
one did no work, so it is shown as refused and never counts toward the cap; a
run that stops on the limit and is resumed nine times is not stopped by the
cap for it:

    2 calls, 9 refused, 28 tokens counted (input 20, output 8) (cli x2)

a failed go the provider gave no count for at all, a timeout say, is still a
call.

### the budget plan

the cap says when a run has spent too much, and says nothing before that. so
before step one a run splits what its cap leaves into a block per step and
writes them to `runs/<id>/budget-plan.md`: the cap, the unit, where the
estimates came from, a realism note, then one line per step and the buffer.

    # budget plan

    cap       100000 tokens, 25 calls
    unit      tokens
    estimate  measured shares of a run's spend: worker 41%, patcher 22%, tester 14%, verify 11%, planner 8%, reviewer 4%
    realism   a split, not a forecast: no earlier run of this flow here says what its steps take, so the cap is shared out by the measured shares

        step        estimate
        planner.md  11428
        worker.md   58571
        tester.md   20000
        buffer      10001

an estimate is what the step took in the newest five earlier runs of the same
flow on the same project: the token cap's count (input, cache writes and
output) when those runs were counted, else the calls. a step none of them ran
is scaled from the ones that did by the shares below. with no earlier run at
all, a token cap is split by the share of a run's spend each role took,
measured over earlier runs of the shipped flows (worker 41%, patcher 22%,
tester 14%, verify 11%, planner 8%, reviewer 4%; a role not on the list gets
the mean), with a tenth held back as the buffer. a flow with only a call cap
is planned at one call per step, and a fanned-out step counts once until an
earlier run says how wide it went.

when the blocks do not fit what the cap leaves, the run says so before it
calls anything, and the plan file ends with the same line:

    RISKY: the steps take ~3 calls, the call cap leaves 2 (budget-plan.md)
    RISKY: the blocks add up to ~115000 tokens, the token cap leaves 100000 (budget-plan.md)

RISKY is a warning, not a stop: the cap still stops the run where it always
did. the realism note then names the biggest block as the first place to save,
and says the red test is never where the saving comes from. a plan that fits
reads `comfortable` with a buffer of a tenth of the cap or more, and `lower
bound` under that.

### what a flow gives up when it does not fit

`sacrifice:` in flow.yaml says what may go when the money is short, first to
go first, one step or role per line:

    sacrifice:
      - reviewer-wide
      - verify
      - investigator

when the plan says RISKY, the run cuts from the top of the list, one name at
a time, and stops cutting as soon as the steps left fit what the cap leaves.
a role cuts each of its steps, so `reviewer-wide` is the second of two
reviewer steps and `reviewer` would be both. a list that cannot make the plan
fit cuts nothing, and the run still says RISKY. the same list is read again
when the token cap warns that 80% of it is spent: the steps still ahead are
cut in the same order until their blocks fit the rest of the cap, and the run
goes on; a rest that fits already goes on with nothing cut. if the whole
list would not make them fit, nothing is cut and the run waits at the cap as
it always did. near the cap the blocks have to be an estimate, from earlier
runs of the flow here or one call per step: a plan that only shares the cap
out has nothing to cut on, so the run waits at the cap with nothing cut. a name with no step left ahead is
passed over. a cut lead decides nothing: a question a step asks goes to the
person, saying the lead was cut for the budget.

each cut is a named skip under the name the list gave, with a reason that
says what did not fit:

    cut verify.md: budget: the steps take ~3 calls, the call cap leaves 2

it is kept in `runs/<id>/skips.json`, written to decisions.md, and said in
the handoff with `(sacrifice)` where a `--skip` says `(--skip)`, and listed
again under its `not done`, so a run with cut steps does not read as
complete. the plan file marks the step `cut` and gives the reason under its
table; the manifest keeps the step `not run`.

a run picked up later does not take the cuts over: it plans them again
against the cap it has now. a resume that raises the cap runs a step the
first leg cut when the plan fits with it, and decisions.md says the step is
no longer cut; one that still does not fit is cut again, with the new
numbers.

never on the list, refused when the flow loads: the red test (`tests`,
`red-test`, `red-first`, or a step that writes tests or carries those gates),
the tests the run started with (`start-tests`, or a `writes: product` step,
which is where they run again), the suite gate (`command`, or a step that
carries one) and a check `project.yml` declares (a step that carries a
`project`, `coverage` or `reject` gate), which is how a flow often runs its
suite. nor is a check the flow needs to come out as it said: the verify step
when the flow says `verify: judge`, a step that carries a `verdict` gate, or
one whose prompt asks for a verdict on the spec (`{SPEC_DIFF}` or
`{SPEC_AT_START}`), which is what sends back a spec line moved with no
ruling; that last one is refused when the run starts, where the prompt is
read. any other gate is refused too: a gate spends no calls, so cutting one
saves nothing.

a block is accounting inside the run's total, not a second cap. every line in
`steps.jsonl` carries `budget`, the pass held against its block:

    "budget": {"spent": 35014, "planned": 30000, "buffer": 64966, "risk": "over by 5014, drawn from the buffer"}

a step that passes under its block leaves the rest to the buffer (`ok, 29990
left to the buffer`), and one that goes over draws the difference from it. a
redo is charged to the same block, and a step with no block, such as the
cause step switched on mid-run, draws all it spends. once the buffer is gone
the risk says by how much the run is over its plan. a pass is charged what
was spent from the time the line before it opened to the time its own line
opens: its own calls, which are made before its line opens. a step that asks the lead keeps its own call, though
the lead's line is written first.

## what it cost in money

the tokens go through a price table, `prices.yaml`: USD per million tokens,
per model. the copy that ships is `agentweft/guardrails/prices.yaml`, and its
header says the page it was copied from and the day. a `prices.yaml` in the
directory you run from is read instead, and `PRICES=<path>` names one
anywhere. a table with a rate missing, negative or not a number is refused
with the model and the rate named.

    claude-opus-5-5:
      input: 4
      cache_write_5m: 5
      cache_write_1h: 8
      cache_read: 0.20
      output: 20

the model that answered is priced, not the one asked for, which can be an
alias. input, cache reads, five-minute cache writes, one-hour cache writes and
output each have their own rate; reasoning is part of output and paid once.
`over` and `above` price a model whose rate depends on how long a request's
prompt is, and web searches are priced per search.

a call is left unpriced, with the reason, never priced at zero:

- the model is not in the table (or no model was named at all)
- cache writes came without their five-minute / one-hour split
- fast mode, or US-only inference, which the table has no rates for
- a tiered model whose usage is a sum of requests past the threshold: the
  `claude` cli reports one block per session, and the threshold is per request
- two models in one answer with no usage per model

the journal line carries the money after the tokens:

    3 calls, 360 tokens counted (input 300, output 60), $0.0006 priced, reported $0.0006 (cli x3)
    1 call, 1800 tokens counted (input 1000, output 800), $0.0050 priced, reported $0.0066, they differ by $0.0016 (cli x1)
    3 calls, 1000020 tokens counted (input 1000020, output 0), $1.0000 priced + unpriced: m-other x2 (cli x3)
    1 call, ~1100000 tokens estimated, ~$1.5000 priced (cli x1)
    1 call, ~15 tokens estimated, unpriced: no model named x1 (fake x1)

`priced` is the table's figure and `reported` is what the provider said
(`claude`'s `total_cost_usd`); both are printed and neither replaces the
other. when they disagree past the fourth decimal the line says by how much,
which is how a stale table shows up. a priced total with an unpriced call in
it shows the part it could price and names the rest. an estimated run is
priced from its estimate and carries `~`. money is shown to four places,
rounded half up, and anything above zero that rounds to nothing is
`<$0.0001`.

every step's line in `steps.jsonl` carries `priced` beside `cost`, and the
eval scores carry `usd`, `usd_estimated` and `reported_usd`, so a comparison
of two runs can be read as money per result. a step's `cost` can hold a go
the provider never answered for, priced from its transcript or estimated;
`cost_parts` splits it by kind, and `python run.py spend` adds up `reported`,
`table-priced` and `estimated` apart, so a table's figure is never read as
the provider's.

each step's line also says what it won (`caught`, `stopped`, `delivered`,
`proved`, `decided` or `none`, `journal.md`), read off the run's record (the
red proof, the place before and after the step, `decisions.md`, the gates'
entries), never off what a gate or the model wrote. the retro in
`handoff.md` puts every step's money and seconds against it, with the total
spent on `won none`: the first place to look for a step to cut. it also
sums each role's thinking tokens (`journal.md`, `thinking`). its last lines
put the run's wall beside the seconds of the steps, of the gates
(`gates.jsonl`, one line per gate run) and of the runner, which is the rest,
so the three add up to the wall; then the runner's seconds by phase
(`runner/laps.py`: setup, sizing, before, snapshot, step, trail, police,
asks, checks, after, finish, stop, handoff), each the time the runner spent
in it less the model's and the gates' time inside it, so the phases add up
to the runner's figure. the run's `manifest.json` keeps the same under
`runner`: `{"wall", "steps", "gates", "phases": {phase: seconds}}`.

## the promises

    promises:
      invariants:
        - no file appears in two lists
        - needs me is at most 5 lines
        - every line names a file

these go into every role prompt AND get checked afterwards. the checking is
deliberately dumb - a handful of shapes i can actually assert. anything it
cannot check it reports as not checkable rather than passing quietly, because
a green tick you cannot trust is worse than no tick.

a promise the output cannot show can still be one a gate shows: "the new test
fails on the unpatched code" is the `red-test` and `red-first` gates, "the
whole suite passes" is a `command` gate. a run that finished passed every gate
its steps declare, so those are not counted as not checked, and
`python run.py show <flow>` names the gate beside each one.

## the gates

    steps:
      - role: worker
        must_produce: "FAILS:"

a step can be required to have produced something before the next one runs.
fix-with-test uses it, and that only proves the words `FAILS:` are there. the
patcher waits on the `red-test` gate, which runs the test the worker named in
the run's place and wants it to fail (see `docs/gates.md`), and after the patch
the same gate with `red: false` runs it again and wants it to pass. red before
green is held by these gates, not asked of the prompt. a `red-first` gate on
the patcher then
runs each new test on a temporary checkout of the start commit with only the
test files changed, where it has to fail on an assertion, and on the patched
place, where it has to pass, so that the test fails for want of the fix is a
run on record and not a reviewer's reading of an order nobody committed.

after any step that writes product code, the tests the run started with run
again, as the start commit has them, against the product files as they are
now. a test that was green then and is red now stops the run as a spec
conflict naming it, unless a ruling in `decisions.md` names the test or
quotes the spec line that decides it; a test red at the start is not counted
(`docs/gates.md`, "the tests the run started with, after product code").
which tests were red at the start is the run's suite baseline, kept as
`runs/<id>/baseline.json` and cached by start commit; `baseline: on | auto |
off` says when it is read, and the handoff names a test red when the run
started as that, never as the run's doing (`docs/gates.md`, "the suite as
the run found it").
"do not edit the tests you were given" is a sentence in a prompt; this is a
pytest run.

the edit itself is caught at the step that makes it, too: after every step a
test file the run started with is compared per test function against how the
run found it, and a test removed or changed, or its file deleted, fails the
step like a gate and parks the run for a ruling on its last go. a test added
beside the others passes. a ruling that names the test, quotes the spec line
that decides it, or answers `override:` to that park lets the change stand;
one that only names the file does not (`docs/gates.md`, "the tests the run
started with, as it found them").

## the spec files

    # flow.yaml
    spec_files: read-only

a step that cannot make the work match the spec can make the spec match the
work. `spec_files:` says what a step may do to the spec files (`TASK.md` or
`SPEC*.md` at the top of the place, or a file under `docs/spec*` there), and
after every step the runner reads them against how the run found them:

- `read-only` (fix-with-test): any change, added lines included, fails the
  step the way a gate does (`spec-files` in `gates.md`, the files named). it
  goes again once with that at the end of its prompt, and the run stops
  `gate failed` if the file is still changed. a fix is checked against the
  spec, so the spec is not the fix's to move.
- `additions` (build-feature): a new line passes, and `gates.md` says how
  many were added. a line the run started with that is removed or rewritten
  parks the run for a ruling, cause `parked`, outcome `needs you: ruling`,
  with each line quoted in `question.md` as it was and as it is now:

      - TASK.md:3 - was "the report lists students in the order given.", now "the report lists students alphabetically."

  an entry in `decisions.md` that quotes the line (all of it, or three words
  of it or more, between double quotes) lets the change stand, and so does an
  `override:` answer to a question the runner asked that named the line: this
  park, or a spec conflict whose quote it checked, which authorises the lines
  it cites. the runner knows its own question by what it wrote in the leg's
  `manifest.json` when it parked, never by the question's words, so a step's
  own question that quotes a spec line, answered `override:`, rules nothing.
  any other answer goes to the step, which runs again; an answer starting
  `request:` never rules one.
  the check waits for the step's other gates to pass, since a failed one
  sends the step back anyway.

the text a spec file had is read from the start commit, or from the start
snapshot for a file already loose or a place with no commit, and which files
changed from content hashes. so a step that commits its edit is read the same
as one that leaves it in the work tree. blank lines and trailing spaces are
not lines. a flow without `spec_files:` is not checked, and the handoff's
rulings section still lists a changed spec file as before. a reviewer reads
the spec as the run found it and the diff since (`{SPEC_AT_START}` and
`{SPEC_DIFF}` in `flows.md`), and its ok on a spec that moved with no ruling
is a redo; under `additions`, added lines do not count.

## the rulings only the runner writes

the start-tests replay, the spec-files rule, the reviewer's spec diff and a
conflict's `override:` all let a change stand on an entry in `decisions.md`,
and `decisions.md` is a file in the place. a step with file tools could
write the ruling that lets its own change through, so the runner keeps its
own record, `runs/<id>/rulings.json`, outside the place: a sha256 of every
entry that was there when the run started and of every entry it writes
itself, from `--answer`, the lead's decision or a raised cap, with who wrote
it (`answer`, `lead`, `cap`). every check that reads a ruling, and the
handoff's rulings section, reads only the entries in that record. the
checks that let a spec line or a start test change, in its file or its
result, skip the `lead` entries: a lead decides inside the spec and the
tests, never over them. a resume
carries the record of the run it picks up, so those entries stay the
lead's; when that record is gone or cannot be read, no entry already in the
file counts as a ruling on that leg, since none can be told apart.

a check reads what an entry itself says, never the question it answered or
the stop it carried on from: for `--answer` the heading and the answer, for
the lead the heading and its `DECIDED:` and `why:` lines, for a raised cap the
heading alone, and for an entry written by hand all of it. only an
`--answer` reaches into its question, for what that question cites (the spec
line of an `override:`, a test its quote of the spec decides, the tests of a
test-edit park). so a lead decision on a question that cites a test, or
quotes a spec line, says nothing about either; and since those checks skip
the lead's entries, not even its own lines naming the test or quoting the
line let it change.

the answer of an `--answer` entry is read after the last `answered:` line,
and only in a body that ends the way the runner ends one (`answered by <who>,
with --answer`). a step's question comes before the runner's marker, so an
`answered:` line and an `override:` a step wrote into its own question are
read as the question, never as the person's answer.

after every step the file is compared with what the runner last wrote, and
again once the step's gates have run, since a gate runs code the step wrote:
a change made there is the step's, not the next one's. a step that added,
edited or removed an entry fails the way a gate does (`rulings` in
`gates.md`):

    decisions.md was changed by worker.md; rulings come only from --answer or the lead. ...

the file is put back as the runner left it, so the forged lines count for
nothing, and the step goes again once with that at the end of its prompt.
this is read before anything else the step said: a `NEEDS:`, a `CONFLICT:`,
a `REFUSED:` or a `WRONG TEST:` from a step that changed the file is not
acted on, so a stop cannot hide the change. a step that changed the file and
also crossed the fence, answered nothing, hit the provider's limit or crashed
still stops for that, and the stop's reason and the step's line carry the
`rulings` failure beside it. a
lead that writes the file instead of deciding has not decided, and the
question goes to the operator. a stop runs the tests the run changed, and
that is code a step wrote too, so the file is checked once more after them:
a change there is put back, and why.md and the handoff say "decisions.md was
changed by the tests the stop ran". entries already there when the run started
count: between runs the file is the person's, and a ruling written by hand
is theirs.

before it gets that far, a `claude` step granted `write` or `edit` has the
shell-write hook on Write, Edit, MultiEdit and NotebookEdit too, refusing a
call whose `file_path` (or `notebook_path`) is `decisions.md` in the place
and letting every other path through; a step granted `shell` already has
every shell write refused. the record is what holds when the hook does not
reach: a step on another provider, or a write the hook cannot see.

## the facts only the runner writes

the facts under `facts/` in the place (`docs/journal.md`, "what is known
about a file") tell a step what a file's way is, so a step that could write
one could write the fact that lets its own change through. they get the
same three walls as the rulings, in `agentweft/guardrails/factsguard.py`.
the store is every `.md` file under `facts/`: the entry files, `INDEX.md`
and `PROPOSED.md`. those names are reserved. any other file there, a
project's own `facts/capitals.json` say, is the project's: no wall stands on
it, a check reads it, and a change to it is a change to the product.

- the account, `runs/<id>/facts.json`, outside the place: a sha256 of every
  entry under `facts/` when the run started (after the start's heal, which is
  the runner's) and of every entry the runner writes, and the reason for
  every fact it refused. a place with no `facts/` and nothing proposed leaves
  no file. an entry written by hand between runs counts. it also lists under
  `applied` each file outside `facts/` the runner changed for the retro, a
  doc edit or a test guard (`docs/writing-a-flow.md`, section 10), with the
  sha256 of its bytes: a leg that carries the run on reads it, so a file
  that still holds those bytes is no product change, no new test of the
  run's, nothing the fence guards and nothing a step commit takes.
- after every step, and again after its gates and after a stop's test run,
  the store is compared with what the runner last wrote, in the same check as
  `decisions.md`. a step that added, edited or removed a store file fails
  the way a gate does (`rulings` in `gates.md`):

      facts/pkg/a.py.md was changed by worker.md; facts come only from the runner. added or edited F-0003. it was put back, and the change counts for nothing

  and the store is put back as the runner left it, a file the step added
  taken away.
- the hook on a `claude` step's Write, Edit, MultiEdit and NotebookEdit
  refuses any `.md` path under `facts/` in the place, as it refuses
  decisions.md.
- two runs on one place started from the same folder share a ledger in
  `runs/` (`facts-ledger-<key>.json`, with its `.lock`): what each run last
  wrote to every store file. one run's check takes what the other wrote as
  the runner's and keeps it, so neither puts back the other's facts, and a
  step's change is still put back. writes and checks on the place take turns
  under the lock, so two runs never write the same id.

a fact the runner is asked to write is held to the record before anything
is written; a refused one is not written and its reason is kept:

1. no field may look like a secret: a token of a known shape (`sk-`, `ghp_`,
   `AKIA...`, a private key block, a JWT), a file that holds one by its name
   (the brief's credential names and the police check's), or a string of 32
   or more letters and digits that mixes cases and reads as random. the
   reason names the field and the kind, never the value. a claim, why,
   source or check that names a path on the machine the run ran on is
   refused the same way (`it names a path on the machine it ran on (<path>)
   in <field>`), and a check refused for its form whose reason names one is
   kept as `unchecked: its check was refused: it names a path on the machine
   it ran on`, never the reason's own words:
   one that starts at a drive letter (or Git Bash's `/c/` for it), at a
   share's two backslashes or two slashes (by name or address), at a home
   folder's tilde, or at a file-system root such as home, Users, tmp
   or var, never a URL or a request path such as `/index.html`. the store lives in
   the repo, read on every other machine; so does a doc edit's `after:` and a
   guard's `code:`, `what:` and `where:`, held to the same rule, and no line
   of `facts/PROPOSED.md` is written that holds one.
2. a one-line claim and a why, no `|` in any field, a kind from `decision`,
   `convention`, `why`, `defect`, `gate-issue`, a label from `important`,
   `wip`, `investigation`, `pins` or none. a `gate-issue` that names an OS error code
   (`WinError 87`, `Errno 22`) is refused: it is what the machine raised as
   the run went (`gates.md`, the fault a gate runs once more), not the
   project's, and a later run on a sound machine would be handed it. a
   `convention` or `gate-issue` whose claim or why names the run's own host
   ("this machine", "this shell", "the step's shell", "this Windows" and the
   like), antivirus or an OS error code is refused the same way, and so is a
   `gate-issue` that names a shell or toolchain (Git Bash, PowerShell,
   `cmd.exe`, MSYS, MinGW, Cygwin, `python -c`, a heredoc), or a convention
   that names one beside a second one, its quoting or escaping, or a word
   that it failed (broke, failed, mangled, lost and the like: "`python -c`
   with nested quotes broke under Git Bash"). a convention may otherwise
   name those for the product ("the release scripts are PowerShell modules",
   "paths use forward slashes on Windows and Linux", "the CLI starts no
   shell"): that is not the host, and it is written.
3. every scope is in the place: the file, the folder, a file a glob matches,
   or `.`. a scope that is absolute, starts with a drive, names `..` or
   leads out of the place through a link is refused (`the scope ../ is
   outside the place`), so an entry is only ever written under `facts/`.
4. its evidence is on the record: `<file>:<line> "<quote>"` with the quote at
   that line, as the run found the file or as it is now. the quote runs to
   the last `"` of the evidence, so a code line's own quotes stay in it,
   and it holds when it is at the line as written or with `\"` read as `"`
   (and `\\` as `\`); a quote that ends at an inner `"` with more words and
   another `"` after it is cut short and refused. `<command> exit
   <code>` with a gate of this run that ran that command to that exit code;
   or `decisions.md <stamp>` with a ruling the runner has on record at that
   stamp. anything else does not hold.
5. its anchor names lines the file has, in the place by the same rule as a
   scope, for a new fact and for a re-anchor alike; the runner hashes them
   itself, and a hash written in the proposal is ignored.
6. the same claim on the same scopes as a live fact is counted on that fact
   (`seen: proposed 2, ...`) instead of written again.
7. at most three new facts a run (`per-run cap`); a supersession is a new
   fact, and marks the one it replaces `superseded`. the one fact the
   runner writes from its own record is outside the cap and held to every
   other rule here: the tests the last red-first gate that passed ran green
   without the change, as one `why` fact labelled `pins` on their test
   files, its evidence the first one's `def` line (`written: ... by runner
   from the red-first gate`). a fact the retro proposes that is labelled
   `pins`, or that sits on one of those test files and names one of those
   tests, is refused as that note again. a new fact whose only scope is `.`,
   the whole project, or a glob such as `**` that matches every file, is
   refused once the project has eight live ones (`the
   project already has 8 live project-wide facts, ...`): each is handed to
   every step on every file, so it is scoped to its files, or one of the
   eight is superseded or retired first.
8. a `check:`, when it has one, runs and holds on the place as it is. one
   that does not hold (`the check does not hold on the tree as it is: ...`)
   says the claim may not be true, and the fact is refused. one refused for
   its form alone (`the check cannot run: ...`, `the check reads <path>,
   which is not in the fact's scope`, a `|` in it) is still run wherever the
   runner can run it (a `|` in an `-E` pattern, a path outside the scope but
   inside the place), and one that does not hold refuses the fact the same
   way. an `exits 0` check that finds one of the fact's own anchored lines,
   or with no anchor one of the lines its evidence quotes, is refused for its
   form too (`the check only finds the fact's own anchored line,
   <file>:<line>, so it holds the code's text, not the claim`, `evidence
   line` for the second): one
   matching line holds it, so it never fails on a wrong change and fails on
   every harmless edit of that line. one that cannot run, or runs and
   holds, leaves a fact that held every other test: it is written without the check, with `unchecked: its
   check was refused: <why>`, which the retro's line, the handoff and every
   step handed the fact read too. a convention under 9 is not: its check is
   what holds it.
9. a `convention` whose claim says every, each, all, always, never, none,
   nowhere, only, single, sole, any or no is written only with a check that
   holds on the tree, and one a line against the claim breaks: `exits 1`, a
   pattern no line may match. the words are read outside the claim's code
   spans and as words: python's `None`, a `--no-` flag, a `no-op` and "no
   longer" (or more, less, matter, sooner, later) are not one. one with no
   check, or with an `exits 0` grep, which holds by one line and never by
   every one, is refused (`a convention that says every is kept only with a
   check that holds on the tree ...`). a why, decision or defect saying the
   same words is not held to it: it explains one place and is kept by its
   evidence, and a true one of those kinds (a premise such as "correct
   only for values of 0 or more", "no test pins it") often has no grep that
   could hold it.

### a fact's check

a fact can carry a program the runner holds the place to:

    check: grep -n "print(" pkg/parse.py exits 1

it is one grep, `grep [flags] <pattern> <path>... [exits <n>]`, and the
runner reads and runs it in its own process: no shell, no process, so a
check a model proposed, or one in a project cloned with its `facts/`, can
run nothing. the flags it takes are `-n`, `-r` / `-R`, `-E`, `-F`, `-i`,
`-w`, `-q`, `-s`, `-H`, `-h`, `-l`, `-e <pattern>` and `--include=<glob>`;
without `-E` or `-F` the pattern is a basic grep pattern, so `print(` is the
text `print(`. `\<` and `\>` are the edges of a word, `\w`, `\W`, `\s`, `\S`,
`\b`, `\B` and `\1` to `\9` read as grep reads them, a backslash before a
mark is the mark, and a backslash inside `[...]` is itself; any other escape
(`\d`, which grep reads as a plain `d`) and a `[:class:]` cannot run. `exits 1` means the fact holds when no line matches, `exits 0`
(or no `exits`) when one does. every path is a file or, with `-r`, a folder
in the place and in the fact's scope; a recursive read never looks in
`.git`, caches, installed packages (`node_modules`, `venv`, `.venv`), the store's `.md` files (which quote the very lines its checks look for)
or the runner's own folder. anything else, a path outside the place, a file
that is not there, a flag it does not take, a pattern that does not read,
another command, `;` or `|` in a path, cannot run. so does a check whose
paths and `--include` globs leave no file to read (`it read no file`): no
line matched, but nothing was looked at, so an `exits 1` would hold on
nothing. when a fact is written such a check refuses it, `exits 0` or
`exits 1` alike (`the check reads no file, so it shows nothing of the
claim`), and after a step it is `could not run`, never `held`.

after every step, with its gates, the runner hashes the files in the scope
of each live fact with a check; when they changed since the last step, the
check runs, and the step's line in `steps.jsonl` gets `conformance`, one
entry per fact: its id, scope, claim and check, the `result` (`held`,
`broken` or `could not run`) and what it `said` (`grep exits 0, the fact
says 1: pkg/parse.py:5: print(...)`, the first line that matched). a step
that left the scope alone runs no check. a check that could not run is
never counted as one that held: it is said on the line and in the handoff,
and counts as neither honoured nor contradicted.

    conformance: warn

the default: a broken check is said and the run goes on. the handoff lists
each fact whose last check in the run did not hold under "not done" (`a
fact's check broken at the end of the run:`), and every check that ran under
`## conformance`; the retro is handed the ones that broke or could not run.

    conformance: fail

makes a broken check a gate, `conformance`, that fails the step and sends it
back like any gate (`send_backs` times, then the run stops on it). the scope
is held as it was before the break, so the step's next go is checked again
even when it leaves the file alone. a leg that picks up such a run runs
every live fact's check as it starts and holds the ones still broken the
same way, so the break the last leg stopped on is not let through because
the next go leaves the scope as it was; a fresh run holds no step to a break
it found. a check that could not run passes with an `issue`
(`docs/gates.md`), never as one that held. any other value is refused when
the flow loads.

a check that reads a path outside its fact's scope, one written by hand
say, cannot run after a step either, as it is refused when the runner
writes a fact.

once the leg ends, each fact's `seen` line counts the steps whose change
held its check (`honoured`) and broke it (`contradicted`), and a pass sent
back with a `CONVENTION:` line naming the fact's id counts as
`contradicted` too (`docs/journal.md`).

## the files that brief the model

a `cli` step starts its model in the run's place, and a model cli can take
what it finds there as instructions or config: a `CLAUDE.md` or `AGENTS.md`
at any depth, the `.claude/` directory, a `.mcp.json`. so a step that writes
one of those has written the next step's instructions, and the next step's
prompt says nothing about it.

the run takes a digest of those files when it starts, and before every step
whose model is started in the place it takes another. anything written,
edited or removed in between and the step does not start: the run stops with
`failed at <step>` and the cause `refused` in the journal, the files named in
its why, a `REFUSED` line in the index, and the files named on stdout. `guardrails/briefing.py` is the
list.

what was there at the start is what the run was pointed at, and it is not
questioned. a step on the `api` or `fake` provider sends text and reads
nothing in the place, so it is never refused for this. every start takes its
own digest, `--resume` included, so a file a step wrote before a park is
something the person who carried the run on has let through. `.git/` is not
walked, and nothing above the place is looked at.

## the scope fence

    # project.yml
    fence:
      skip: ["**/__pycache__/**", ".pytest_cache/**"]

the rule is recoverability, not permission. a file git tracks can be put back
from git, and a file this run created did not exist before it, so a step may
touch both. a file that was in the run's place before the run started and
that git does not track has no copy anywhere: a `.env`, a local fixture, work
nobody has committed. that is the one case the fence is for.

the run lists the untracked files in the place when it starts, ignored ones
included, and keeps a digest of each. after every step it asks `git status`
again and compares. one of those files changed, removed or now tracked (a
`git add` is as much a hazard for a `.env` as an edit) and the run parks:
`fenced at <step>` and the files on stdout, the files again in the handoff, a
`PARKED` line in the index, `parked at <step>` in the journal. `--resume`
carries on after that step, and takes a fresh list, so what the person has
looked at and let through is the new starting point. a scored run stops with
`fenced at <step>` as its reason.

the block being in `project.yml` is the switch: no block, no fence, and
`fence: {}` is a fence that skips nothing. a bare `fence:` is refused rather
than read either way. `skip` takes git globs relative to the place, for the
things a test run rewrites every time. a place git knows nothing about with a
fence declared is refused before the first step, because there is nothing to
tell a file git can restore from one it cannot. the run's own `runs/` folder
is left out when it sits inside the place.

it is the boundary only. nothing intercepts a tool call; it compares before
and after, so it catches mistakes and not a determined agent with a shell,
which can write outside the place or into a skipped path. it is not a security
boundary. the gates a step runs are commands in the same place, and what they
touch shows up at the next step's check, and after the last step at none.

## the sign-off

    python run.py build-feature --task "..." --target main

a run that got through every step and changed files in a git repo is signed
off only if its change still merges onto the branch it is for. the branch is
the one `--target` names (a local or remote-tracking branch). without it, a
run in a worktree of its own (`--worktree`) is for the branch checked out in
the person's tree, which moves as the person keeps working; any other run is
for the upstream of the branch checked out, since the branch itself cannot
move without HEAD moving with it. a branch with no upstream and no
`--target`, or a detached HEAD, has nothing to check against, and the
handoff says the change was not checked. a resumed run keeps the branch, and
the head, it started for. heads are read as the repo has them: nothing is
fetched.

a `--target` git does not know, or one given in a place that is not a git
work tree with a commit, is refused before the first step.

the run's change is HEAD now with every file that differs from what the
tree held at the start. a file that was already loose when the run started
and still holds those bytes is the person's, not the run's, and is left out.

- not moved: nothing more is said.
- moved, and the change merges onto the new head with no conflict: the run
  is `done`, and the handoff's checks say `sign-off: main moved to <sha>
  since the run started; the change was re-checked on it and merges with no
  conflict`.
- moved, and it conflicts: the run stops, cause `target moved`, outcome
  `stopped: target moved`, `stopped at <last step>` in the journal. the why
  and the handoff name the files and say `rebase onto main (<sha>) and
  settle <files>, then carry on`.

the same check runs before every step, so a step is not paid for on a change
that no longer merges: the branch's head is read again (one `git rev-parse`),
and only when it moved since the last read is the change merged onto it, as
above. a conflict, or a check that cannot be done, stops the run before the
step, `stopped at <step>` in the journal and `stopped before <step>` in the
handoff; carrying on starts at that step. a head that moved and still merges
is printed, `sign-off before <step>: main moved to <sha>, and the change
still merges onto it`, and the run goes on. a run with nothing to check
against is not checked before its steps either; its handoff says so at the
end, as above.

the check is read only. it asks `git merge-tree --write-tree`, with an index
and an object folder of its own in a temporary folder (the repo's objects
read through an alternate), removed after. the person's tree, index, HEAD,
branches and object store are as they were, and nothing is staged or
committed in them. anything more than that is not done, and the run stops,
cause `merge unchecked`, outcome `stopped: merge unchecked`, `stopped at
<last step>` in the journal, with the why saying to check by hand: git that
cannot read the place at the end, a branch that cannot be read now, a
changed file git reads through a filter program (an lfs: a program outside
git that may write where it likes), or a git without `merge-tree
--write-tree` (2.38 and later).

## the off task check

    # flow.yaml
    police: on
    network:
      - installs
      - pypi.org

off unless a flow says `police: on` (or `shadow`, below). after every step on the `claude` cli the
run reads the step's transcript, the one the handoff takes its read lines
from, and holds each tool call to four tripwires. no model is asked, so it
costs no tokens; what it found and the seconds it took go on the step's line
in `steps.jsonl`:

    "police": {"hits": 0, "seen": true, "seconds": 0.004}

- `grant`: a call to a tool outside the step's `tools:`, an mcp tool
  included. declared, enforced and called have to agree, so a grant on a
  provider that does not hold the step to it, a cli other than `claude`, is a
  hit before any call is read.
- `network`: a shell call that installs a package (pip, uv, npm, pnpm, yarn,
  cargo, apt, brew, gem, go; `python -m pip` and `py -m pip` too), pipes what
  curl, wget or a PowerShell web cmdlet fetched into a shell or `iex`, or
  reaches a host that is not this machine: a url handed to a network tool, git
  or an interpreter, or a host handed to curl, wget, ssh, scp, rsync, nc,
  `Invoke-WebRequest` / `iwr` or `Invoke-RestMethod` / `irm`. a tool is read
  by its file name in any case and without `.exe`, `.cmd` or `.bat`, so
  `tools/CURL.EXE` is curl.
  `network:` lets them through: `installs` the installs, a host that host and
  the ones under it, `any` every host. a fetch or push to a git remote named
  without a url reaches a host nobody named, and only `any` lets it.
- `credentials`: a read of a file that holds a secret by its name: `.env`
  (not `.env.example`), anything under `.ssh/` but a public key or
  `known_hosts`, `.aws/`, `.azure/`, `.config/gcloud/`, `.kube/`, `.netrc`,
  `.git-credentials`, `.pypirc`, and the claude cli's `.credentials.json`. a
  Read, a Grep on the file, or a shell command naming it, other than `ls`,
  `stat`, `test` and `rm`.
- `instructions`: text the step read, in a file or in a tool's output, that is
  addressed to an agent (ignore previous instructions, you must now, a note to
  the ai or the assistant) and names an action - a command, a package, a host,
  a file to write or a test in it to mark, skip, xfail, deselect, disable or
  decorate - that the step then took. the address alone is not a hit
  and the action alone is not one: it is the read naming the call that came
  after it. an action the step's own prompt names is its task and does not
  count.

a hit stops the run: `parked at <step>` with the cause `off task` in the
journal, the outcome `stopped: off task`, the tripwire and the quoted evidence
as its why, every hit in `runs/<id>/police.md`, and the handoff ending on the
command that carries on:

    off task at worker.md: network: Bash "pip install leftpad" installs a package, and the flow's network: does not let it

the lead's go at a question (`journal.md`, when a step asks for a ruling) is
a call like any other: it is read as soon as it answers, and its own line
(`decided`, `escalated` or `overruled`) carries its `police` field. a hit there stops the run
before the step that asked goes again, its decision not held, with the lead
named in the why: `off task at worker.md: planner.md credentials: ...`.
the step that asked did no work, so carrying on runs it again rather than
going past it, as it does after a step's own hit.

the retro (`writing-a-flow.md`, "say whether the run looks back") reads the
place too, so its transcript is read the same way, held to its read grant,
and its line carries the same `police` field. it comes after the handoff, so
there is no run left to stop: a hit fails the retro instead, `off task:` and
the tripwire as its why on its line, the hit in `police.md` under `##
retro.md`, and nothing in its FACTS block is acted on, so a retro steered by
what it read writes no fact. a retro whose call failed before it answered (the
provider refused it, the call raised) has no answer to read, and its line
says so: `"police": {"seen": false, "why": "the call failed"}`, with
`"mode": "shadow"` in shadow, so no reader counts it unpoliced.

`police: shadow` reads every step the same way and stops nothing. each hit is
written to `runs/<id>/police.md` as it is found, printed as `police (shadow):
<step> <tripwire>: <evidence>`, listed under "not done" at the top of the
handoff, and again in its `## police` section, which says `no tripwire hit on
<n> steps read` when there was none, counting only the steps whose transcript
it read, and `<n> steps not read (no transcript), so not checked` for the
rest: a step it could not read is never counted clean. the step's line in
`steps.jsonl` carries
`"mode": "shadow"` beside its hits. a retro's hit in shadow is in `police.md`
and printed, never in the handoff, which was written before the retro ran,
and its FACTS block is acted on as with police off. it is the mode to learn
what the check
would stop on ordinary work before a flow turns it on. any value of `police:`
other than `on`, `off` or `shadow` is refused when the flow loads, and one
that reaches the runner anyway is read as `on`.

on or in shadow, text a step read that is addressed to an agent and names an
action (the passage the `instructions` tripwire reads), where the step then
took none of the actions it names, is reported and never a hit: one line
under "not done" and in the `## police` section, naming the steps that read
it, the file and its lines (a Read numbers them) or the call whose output held
it, and the passage's first line quoted:

    worker.md read text addressed to an agent at pkg/parse.py:33-36 and took no action it names: "# Release checklist for automated agents: ..."

a passage read twice is one line. it is not a verdict on the text, and it
only names what the tripwire's reader parses: an address with no command,
package, host or file to write in it is not listed.

`--resume` carries on after the step, as it does after the fence: the person
has looked at what it did and let it through. a hit in a lead's answer stops
the run at the step that asked it, once that step has gone again. a step whose transcript cannot be found is
said, `police: <step> left no transcript to read`, and its line reads
`"seen": false`: unseen, not clean. a step on `api` or `fake` sends text and
runs no tools, so there is nothing of its to see.

a resumed run's handoff keeps what the legs before it saw. each leg that has
something to say writes its hits, the addressed passages its steps read and
how many steps were read and not read to `runs/<id>/police.json`, and the
handoff of a leg that picks it up, however many legs on, lists them beside its
own, each marked `(leg <run-id>)`, and counts their steps in both lines. the
retro, read after the handoff was written, is added to the file once it has
been read: in shadow its hits and whether it was read count like a step's.
the same goes into the handoff's police section once the retro has run, each
hit and passage of its marked `(after this handoff was written)`, and a count
that takes it in saying `the retro after this handoff was written among
them`. with `police: off` nothing is written.

the mcp server hands a client a policed run's files wrapped as data
(`mcp.md`).

### what it cannot see

it reads what the transcript says was called, after the call. so:

- it is not in the path of a call. the install has happened by the time it is
  read; the stop buys the record and the halt, not the undo.
- a shell command is read as words. a script that opens a socket, a url built
  from variables, a host in a file the command reads, an install inside a
  Makefile: none of them name the host or the install where it looks.
- a secret is a file name. a `grep -r` over the place reads `.env` without
  naming it, and `env` or `printenv` print what the environment holds.
- the instruction match is literal: what was read has to name the command,
  package, host or file the step then used. a paraphrase, an action spread
  over two calls, or text addressed in words it has no pattern for gets
  through. text one step read and handed on is in the next step's prompt,
  which counts as that step's task.
- a cli other than `claude` leaves no transcript it can read, so only the
  grant half reaches it. a cached answer made no calls, and a go that ended
  the run on an outage or a fault is not read.

## the boundary check, which is not a sandbox

    steps:
      - role: architect
        tools: [read, grep]

the workflow layer's agents have granted each other a list of tools since they
arrived - the architect gets `[read, grep]` and then argues it in prose a few
lines below, "you are deliberately given no shell and no write access". a step
can say it now, and something reads it.

**what it is not** is the thing the word makes you expect. this runner is not
in the path of the model's tool calls: a provider is handed a prompt and hands
text back, so there is no call here to catch and nothing to refuse. that is a
statement about THIS layer, not about the whole repo - the mcp server does own
a tool it publishes, and it has an allowlist on it because it can.

so a grant is three halves when the cli is `claude`, and two for anything
else, and each is honest about which it is:

- with `claude`, the grant is handed to the cli as its own permission flags,
  and the cli's permission layer is what holds the step to it
  (`providers.md`, "a grant reaches the cli"). this runner passes config; it
  still sees no tool call. a cli below the version that applies those flags
  to every built-in tool refuses the step before it starts.
- the grant is put into the step's prompt, next to the role's own rules. that
  is asking, and asking is the weakest thing in here.
- what comes back is read against it. that is `guardrails/boundary.py`, it is
  the same shape as the preflight - judge the output after the fact - and a
  finding goes to stdout and to `runs/<run-id>/boundary.md` beside the gate
  results.

the check does not stop the run, and that is deliberate rather than unfinished. the
thing being reported has already happened somewhere this code was not; a stop
after the fact would look like prevention and buy a record. so it buys the
record and says so.

the marks are narrow the way the promise checks are. a shell block or a `$`
line is evidence of a shell; a diff is evidence of a file changing, and it
does not say whether the file existed first, so `write` answers for it as well
as `edit`. `read`, `grep` and `browser` leave no mark an output can carry, and
they are listed as unseeable rather than quietly passed - a grant that was
never checked must not read like one that came back clean.

a step that says nothing about tools has declared no boundary and none of this
runs for it. `tools: []` is a step saying it may touch nothing, which is a
boundary, and it is checked.
