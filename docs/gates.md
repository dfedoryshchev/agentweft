# gates

a gate is a check that is a program, not a prompt. it takes the text a step
produced and says pass or fail and why.

the reviewer is a prompt asking a model to be careful. a gate is a thing that
either matched or did not. they are for different jobs and i kept trying to
make the first one do the second.

## using them

    steps:
      - role: reviewer
        prompt: reviewer.md
        gates:
          - gate: regex
            pattern: "^## needs me"
          - gate: length
            max_lines: 40
          - gate: regex
            pattern: "TODO"
            present: false

results print under the step and land in `runs/<run id>/gates.md`. the journal
only hears about a gate that failed, because that one stops the run.

a step's gates run after its answer is read for a question: an answer with a
`NEEDS:` line, a first line of `VERDICT: park` or a `REFUSED:` line parks the
run for a ruling (or ends it, for a refusal that cites the spec) before any
gate sees it. a step that stopped to ask produced nothing to gate; one that
changed the place before it asked has its gates run on that, and parks after
them. a `NEEDS:` whose recommended answer changes no code (the `SIZE:` is
read for the answer its `RECOMMEND:` picks), and that cites no spec line
(`CITES:`), does not park at all: it
becomes a doubt and the gates run as on
any answer (`docs/journal.md`, when a step asks for a ruling). so does a `WRONG TEST:`
answer, which sends a test the run wrote back to the step that wrote it, to be
shown red again by that step's gates, or parks on one the run started with;
an answer naming several tests sends every one that step wrote back in one
round.

a step asked for a verdict is held to the verdicts its own file lists, each a
line of its own: `VERDICT: ok`, `VERDICT: redo` and `VERDICT: spec change
request`. an answer outside that list fails the step the way a failed gate
does, so a redo from a file that only offers ok is not a send-back, and a word
the runner does nothing with never walks on as an ok. a judge whose file lists
`VERDICT: spec change request` and answers it parks the run for a ruling, with
the lines after the verdict as its reason; one whose file does not list it
fails. a judge that finds the request is really a change to the spec says so
as a value, not as prose under an ok.

a `CONFLICT: <file>:<line> "<quote>"` line, with `request: <the request's
words>` on the line after it, is read first. when the quote is at that line as the run found it, or starts there and runs on into the lines of its paragraph (the question then cites them all), the run stops on
cause `conflict` before any gate runs, so a red test the step marked as
contradicting the spec is never something the step is sent back to turn
green. when it is not, a `conflict` result goes in front of the step's gates
and fails it, with what was wrong (`docs/journal.md`, when the request
contradicts the spec). a plan line marked `spec: contradicts <file>:<line>`
with no CONFLICT line fails the step the same way, unless an override the
run holds already lets every line it cites change: those lines are ruled,
and a new conflict on them would ask what is answered. the same holds for a
line a `request:` answer held, given with `--answer` to a question the
runner stopped a leg of this run on that named the line: the spec holds by
that answer, and the mark names the question already asked (a behaviour
left unbuilt under the ruling). that holds only for a behaviour whose
`file:` line, before or after the mark, says the plan builds nothing: it
names no file but the runner's own (`decisions.md`, the facts store) or
says none. a held mark on a behaviour whose `file:` names a file of the
place, names no file and is not none, or that has no `file:` line fails the
step, told to leave the behaviour out or say `file: none`, since nothing is
built against a line the spec holds. such
an answer still lets no spec line change. a cite of
`decisions.md` (`ruled override at decisions.md:152`) names where the ruling
sits, not a spec line, so it is passed over and is never a line a ruling
covers. a mark on any other line, or citing no spec line, still fails it.

the lead's own `QUESTION:` is the lead's to decide: its `RECOMMEND:` is
put on record as the lead's decision, every later step is handed it, and
the handoff lists it first under the one decision for the operator to
overrule (`writing-a-flow.md`, section 8). it stops the run for the operator
only on a risk the runner finds on the page, each read off a typed line or
a file, never off the question's words:

- a `spec: breaks` or `spec: contradicts` mark on a line no answer of the
  run already ruled on: a ruling that lets it change, a `request:` answer
  to the runner's own question that holds it, an `override:` whose one
  `` `a` to `b` `` rename in the request the line restates (it holds `a`,
  as every line that override named does; the spec-files check then holds
  the edit to that replacement, `guardrails.md`), or a mark of the same
  kind on the same lines in a question already answered. every such mark goes in
  one stop, and a mark whose cite cannot be read parks too. so does a
  behaviour's `spec` line in none of the five taught forms (`allows`, `adds
  to`, `nothing in the spec`, `contradicts`, `breaks`): no colon, bold, or
  another verb (`break`, `broken`, `violates`) parks it as a mark, with or
  without a question. an `already
  at` mark whose quote is on that code line, with its `fix:` behaviour, is
  fixed test-first instead, the recommendation deciding how; a plain
  `breaks` of that same spec line on the same page is the same breach on
  the new path and is fixed with it.
- the question, a line it cites, its `SETTLED BY:` or its `RECOMMEND:`
  names a test file the run started with. the start snapshot types the
  file, and a name matches it however it is spelt: a bare file name (by its
  last parts), `./`, either separator, an absolute path, any case. with no
  hashed snapshot, any name the snapshot's path rule takes for a test, in
  any case, counts. it parks as the
  test question, naming the test whose code holds a cited line, and an
  `override:` answer naming that test lets the change to it stand at the
  test-edits check, so a recommendation never designs around a start test
  unasked.
- a `SPLIT:` line under the question: `the request "<its words>" reads as
  <one>, or as <the other>`, or the same with `TASK.md:<line> "<the
  line>"`. any such line parks; the stop says whether the quote, three
  words or more, is in the request or on that one spec line as the run
  found it.
- a line of the block that opens with a key a question carries
  (`QUESTION`, `SETTLED BY`, `SPLIT`, `RECOMMEND`, `SIZE`), with a capital,
  that the block's reader does not take as that key: bulleted, or with
  `-`, `=` or nothing for its colon. the reader drops such a line, so it
  parks, said `(not read: ...)` under CITES.
- a `RECOMMEND:` that holds no choice to record: its words, markdown,
  brackets and quotes taken off, empty, `nothing`, opening with a
  placeholder (`none`, `n/a`, `tbd`, `unknown`, `no recommendation`, `-`,
  `?`), ending as a question, or handing the answer to someone else in any
  sentence (`The person names a date`, `ask the user`, `the owner's call`,
  `up to the operator`). these words only ever send a question up; any
  other recommendation, however short (`escape it`), is the lead's
  decision.

the `SETTLED BY:` line is the reason recorded beside the decision, never
its gate. the record names it when it quotes a line of the place as the run
found it (three words or more, a heading marker, a list dash or a table bar
no word, the cited lines one paragraph; a quoted code line may hold `"`),
the operator's answer of this run in decisions.md (below), the request by
name, `the request "<its words>"`, three words or more of the request as
the run holds it (the request as given and each amending answer apart),
or else an answer that handed the call back. any other reason, missing,
misquoted or a heading, leaves the decision standing, and its record says
no spec mark, start test or split sent it up. every file the runner itself
writes into the place, decisions.md and the facts store, is never a place
line, and the run folder's `task.md` is no file of the place. the floor: a
gap two readings of which change what is built, that the lead does not type
as a SPLIT and that names no start test, is decided and listed first; no
check reads whether a recommendation is right, only the operator reading the
handoff's first lines, and the spec-files check and the start-tests replay
hold what the build changes. a second floor: an `ASSUMED:` item is never checked by a gate and
never parks. the template tells a step that a gap two readings of which
would change an output a test checks is a QUESTION even when a like line
points to one, and only a choice no tested output turns on is ASSUMED, but
nothing reads which one a step chose: a real gap filed as ASSUMED goes
ahead, shown only among that step's ASSUMED lines. on a resume, an answered mark is matched by the lines
it cites and its kind, never by its words, and a reworded question names
the operator's answer as its reason by a SETTLED BY line quoting it in the
entry `--answer` wrote in this run (its digest among the runner's own
records of what it wrote), cited by line number or by the entry's stamp
(`decisions.md:2026-11-15 11:40 "<words>"`, the colon may be left out):
the lines of the operator's answer, never the entry's heading, the question
it repeats or its closing line. an answer line quoted whole counts however
short (a one-word answer), any other quote of it needs three words. in a
flow that names a lead, an answer that opens with `you decide`
(any case, with or without a colon and more words) hands the call back (in
a flow with no lead it decides nothing: `--resume` takes no leg, prints the
question with "this flow names no lead to decide it", and the run stays
parked), read
off its first two words and never off what the rest says: a later
decision of the lead's with no other reason names the line of decisions.md
the answer starts on. when the run stopped on the lead's own page, every
QUESTION that page asked with a `RECOMMEND:` holding a choice goes on record
as the lead's decision before the lead goes again, under the hand-back, and
the lead is handed them; a page that now answers one of them otherwise says
so on a line `DEPARTS: <the question's first words> - <the new answer> -
<why>`, which goes on record beside the recommendation it had when its
first words name exactly one of those questions, and is listed first on the
head ("departs from the recommendation it stopped on"). a DEPARTS line in
another form, or naming none of them, is said and recorded as nothing. a
decision the hand-back settles is listed on the head as "decided under the
operator's hand-back". a question of that page with no recommendation has
no default. when that page stopped the run on a test it started with that it
names, or on lines of the spec it marks `spec: breaks` / `spec: contradicts`,
the hand-back lets exactly those change and nothing else, read from what
the runner kept of the question in the leg's `manifest.json`
(`stopped.runner`), never from its words: the tests it names by id in a
file the runner kept (a file it kept covers only a change of the whole
file), and each marked line as the run found it (a mark citing no line, a
line that cannot be read or an unread line beside the marks keeps
nothing). the entry says so: "this authorises changing <the set>, and
nothing else". a change to any other spec line or start test parks again.
an `override:` to such a park is read as before. it lifts no
`spec: breaks` or `spec: contradicts` mark on a line the operator was not
asked about, and a question with no `RECOMMEND:` still parks.
a conflict stop and the test-edits check's park (below) hold no
recommendation: a hand-back to either is one go of the lead, which picks
one of the park's two answers, `the request holds` or `the spec holds` for
a conflict, `override` or `put them back` for the test edits, as the first
words of its `DECIDED:` line, word for word (a line naming both, opening
any other way, or taking the pick back with a no after it, is no pick),
with a `why:` line under it. the pick goes on record as the answer it
stands for, with its why as the words: `override:` (on the lines the
conflict cites, or the tests the park names), `request:`, or `put them
back:`, answered by the lead "picking under the operator's you decide".
on a conflict the start tests raised (a test green when the run started,
red against the product now), `the request holds` names each red test of
the question the runner wrote in its `override:`, so the replay lets
exactly those change and a start test the question did not name still
stops the run; a pick that cannot be read stops it again with the start
tests' wording.
the lead's go is priced on its own line of the leg; a pick the program
cannot read, or a lead that escalates, parks the run again on the same
question in a new leg.
any other answer decides its own question only. the step that runs again is
told which marks of its question the answer took, and of a hand-back, that
the call is its to make; only the lead is told its later questions are
decided by its recommendation.

the same holds for every other quote a step gives as evidence. a `REFUSED:`
line and the `spec:` line under each `WRONG TEST:` claim that cite a line that
is there have to quote what that line says as the run found it, or start
there and run on into the lines of its paragraph, the way a conflict quote
may (the refusal and the claim then cite them all); when they do
not, the refusal does not end the run and the claim goes to no one: a `quote`
result goes in front of the step's gates and fails it, naming the quote and
the line (`the WRONG TEST spec: line quotes "...", which is not at
TASK.md:3 as the run found it`), and the step is sent back as for any gate.
a quote of a line the run left as it was is also found at its number now,
where lines the run added above it moved it: each line it reads at is mapped
back to the line it was when the run started. a line the run rewrote or
added is never found that way, and a `CONFLICT:` quote is still read at the
numbers the run found. a claim's quote of spec lines an override the run holds lets change may also
be those lines as the run's own edit left them: each a line the run rewrote
or added where the override lets a line change. a claim on a test the run
started with that the step changed, quoting lines such an override covers, is
no question: it parks nothing, and the test-edits check below lets the change
stand.
a VERIFIED claim in the HANDOFF block written as `<file>:<line> "<the
line>"` is evidence only, so it fails nothing: it is marked `unbacked` with
the same words when the quote is not at that line, and `backed` by the file
when it is and no command was named.

nothing goes past a failed gate, but the run does not stop on the first one.
the step that failed goes again, once, with the gate's line at the very end of
its prompt (`your last answer failed a gate, so this step runs again. the gate
said: ...`), so a patcher that answered in prose and changed nothing is told
the test is still red and gets one more go. it is the step itself that goes
again, not its `on_redo` target: the gate judged what that step produced. the
first try's line in `steps.jsonl` says `gate failed` with `to` naming the step;
the count is kept per step, so one step going again never uses up another's.
if it fails a second time the run stops there as before, and the why says how
often it was sent back and the cap it hit (`... sent back 1 time already
(send_backs: 1)`). a provider failure retried inside one call is not a go and
never spends the count.

once is the default. a flow that wants more, or none, sets `send_backs` in its
`flow.yaml` (`docs/writing-a-flow.md`): at 2 a failing step goes again twice
before the run stops, at 0 the first failure stops it.

a command or red-test gate keeps the last 160 characters of what the command
printed, not the first: a test runner says what failed at the end. the
quote starts at the start of the oldest line that fits whole in them, or at
a word when the last line alone is longer. a section rule pytest drew, like
`=== short test summary info ===`, is drawn again 80 wide first: pytest
draws it to the terminal's width and one column short on windows, so the
same failure quotes the same on every machine.

a command, red-test or red-first gate runs its command with
`PYTHONDONTWRITEBYTECODE=1` and `PYTHONPYCACHEPREFIX` set to a new empty
folder, so python neither leaves bytecode in the place nor runs the bytecode
an earlier run left: a `.pyc` is trusted on the source's size and its mtime in
whole seconds, and an edit of the same size within the same second would
otherwise run the old code.

the same gates, the run of the start tests, the sign-off's git, the bench's
hidden suite and an MCP server a flow reads from start without the provider
credentials the run may hold: every name under
`ANTHROPIC_` and `CLAUDE_CODE_OAUTH_`, and the api provider's `API_KEY`. the
command is the project's and the tests are a model's, so a test that prints
its environment, or a git config that names a command of its own, never
sees a key or a login token. every other name passes as before; a test that
needs a provider credential of its own cannot have it from the run. the
gates' environment also carries the names `env:` in `project.yml` declares
that the place's `.env` set (`orchestrate.md`), and only the gates' does.

every git agentweft runs itself (the snapshot, the fence, the sign-off, the
commit modes, the replay's worktree, the brief's ignore check) starts as
`git -c core.fsmonitor=false -c core.hooksPath=<null device>`: a place's
`.git/config` is the place's, and git would run its `core.fsmonitor`
command on a status and its hooks on a commit or a checkout as you, with
the run's environment. the command line ranks above every config file.
the edit tools of a step in a place are kept out of `.git` (`--keep-all`,
`providers.md`), in any spelling the outside fence reads as the same path
(case, `..`, a link, Git Bash's drive form `/d/...`), and a shell write
into it is refused like any other. that
is two walls, neither whole: a program that writes git's config as a side
effect (`git config`, run by a step with a shell) is not seen by the hook,
and `include.path`, `credential.helper`, `core.sshCommand`, `diff.external`
or a `filter.*` driver written that way would still run on agentweft's
next git. a git too old to take `-c` fails the call, which every site
already reports as git failing.

a step with no gates gets its heading in `gates.md` too, with `no gates`
under it, and its line in `steps.jsonl` says `"ungated": true` (see
`docs/journal.md`). without it, a step missing from `gates.md` could have
had no gates or never got as far as the check, and the file could not say
which.

a fail that is the gate's own says nothing of the step's work, and its
entry in `steps.jsonl` carries `"broke": true`: a command not on PATH, a
gate set up wrong (no command, a `red:` that is neither true nor false, a
`project.yml` that is not there or has no such gate), a red-first replay
that could not build its checkout or start the test runner, a start-tests
replay that could not run on the start state. it still fails the step, and
the step's `won` is not `caught` for it. each gate's seconds go to
`gates.jsonl`, a line per gate run.

a gate that could not do its job says so whether it passed or failed: its
line in `gates.jsonl` and its entry in `steps.jsonl` carry `"issue":
"<gate> could not <what>: <why>"`. every broke fail has one, and so do the
results a gate gives without having checked: a command or test that timed
out, a red-first or start-tests replay with no start commit, a red-test gate
with no `TEST:` line, a coverage report missing or unreadable. nothing about
the result changes: a timeout still fails and a replay with no start still
passes. the retro reads the issues, and the handoff's retro tally lists them.

a test fails too when the machine cannot start a process it runs: an
`OSError` with a WinError or errno code (`OSError: [WinError 87] The
parameter is incorrect`), raised at spawn, which no change to the code can
cause or cure. so the `command` gate, red-first's run of each new test with
the fix, and the start-tests replay (below) read what failed: when every red
is a bare `OSError` with the same code, or the gate could not start its
program on one, they run once more and take that run's result, the pass
saying `run again: the first run failed on <it>`. a fault that holds on the
second run is the gate's issue, `could not run ...: <the fault>`, and a
broke fail. the run stops there with the gate's line and the step is not
sent back: going again would meet the same machine; a scored eval run
stops the same way. only `OSError` itself
counts; its subclasses (`FileNotFoundError`, `PermissionError`) and every
other exception are what wrong code raises too, and stay the change's red
(`guardrails/hostfault.py`). and a bare `OSError` is the machine's only when
it came from the spawn: its code is one a spawn raises (WinError 87, 193 or
2; errno 7, 8 or 12), or its traceback shows the spawn (`_execute_child`,
`CreateProcess`; another frame of `subprocess.py`, a running process's pipe,
is not the spawn). code that removes a full folder
(`[WinError 145]`, `[Errno 39]`), renames across drives (`[Errno 18]`) or
passes a bad argument (`[Errno 22]`) raises a bare `OSError` too, and that
red is the change's: the step goes back with it. red-first's run of each new test without the
fix is held the same way only where the test could not be started at all,
the fault raised before any test body ran: there a red is what it wants, so
a fault inside a test still reads as one.

a gate reads the answer without its HANDOFF block (`journal.md`, "what each
step hands over"): the block is the step's account of the work, and a length
cap or a pattern is about the work.

a gate name that is not one of the ten below, or an option the gate does not
read, is refused when the flow loads, before any step is paid for.

## skipping a gate, by name and with a reason

    python run.py build --skip regex,length "the pattern predates the format"

`--skip <gate>[,<gate>] "<reason>"` turns the named gates off for one run.
deleting the gate from `flow.yaml` would leave no trace in the run; a skip
leaves three:

- every step's gate of that name still gets its line, a pass that reads `not
  run - skipped: <reason>`, in `gates.md` and in the step's line in
  `steps.jsonl`, where it carries `"skipped": true`. a skipped gate proves
  nothing: the step's `won` never counts it as `proved`, the handoff never
  says a skipped red-first gate showed anything, and the checks line counts
  it apart (`1 of 2 gates passed, 1 skipped`). a gate passed for
  `--skip-tests` is marked the same way.
- `decisions.md` in the run's folder gets an entry naming the gates, with the
  reason.
- the handoff's checks line and its "tests and checks" say which gates were
  skipped and why.

the reason is required, so a skip with none is refused before anything runs.
so is a name that is not a gate, one no step of the flow has, and one named
twice. `--skip` can be given more than once, each with its own reason. the
skips are kept as `runs/<run id>/skips.json`, and a run picked up with
`--resume` skips the same gates.

`tests` is one name for the `red-test` and `red-first` gates and the test
order checks together (below), and `--skip-tests "<reason>"` is short for
`--skip tests "<reason>"`. skipping `red-test` or `red-first` by its own name
turns only that gate off: the order checks still want a red proof.

## the ten

- **regex** - `pattern`, and `present: false` to require it is absent.
- **verdict** - an answer of `PASS` and `FAIL` lines. a line that starts with
  `FAIL` fails the step in any list shape (`- FAIL:`, `1. FAIL`, `**FAIL**`,
  any case). a line that starts with `UNSURE`, `NOT SURE`, `UNVERIFIED`,
  `CANNOT CHECK`, `UNKNOWN` and the like is a check the step could not decide:
  neither a pass nor a fail, it is recorded as unproven. the step passes when
  it answered `passes` checks (default 1), at least one of them `PASS`, and
  none `FAIL`; so `PASS a`, `PASS b`, `UNSURE: c` under `passes: 3` passes
  as `2 PASS, 1 unproven, no FAIL`, and the same with `FAIL c` fails. an
  answer in prose, one that leaves a check out, or one of nothing but unsure
  lines fails. an empty answer fails as `the step answered nothing`.

  an unproven check is never silent. its line goes into the gate's entry in
  `steps.jsonl` (`"unproven": [...]`, left out when there is none), into the
  handoff's `## not verified` section as `<step> unproven: <line>`, and into
  the run's outcome: a run that got through every step with one reads
  `done, 1 check unproven` where a clean one reads `done` (the outcomes are
  listed in `docs/journal.md`, "how a run ended").
- **length** - `max_lines`, `min_lines`.
- **command** - `command: [...]`, with `{file}` replaced by a temp file holding
  the output. passes when the exit code matches `expect` (default 0). it runs
  in the run's `workdir` (see `docs/flows.md`), so it can check the work
  itself and not only what the step said about it. a `cold:` block gives it
  a shorter command for a change the risk map says is small (below). a
  command that is not on PATH, or cannot be started (not executable, not a
  program), fails the gate and says so; it is not a tool fault. a step is
  failed only by tests that were green when the run started: a failed
  command whose output is a pytest run naming every red its count line
  counts, each one a start test red when the run started (the suite as the
  run found it, below), passes as `exit 1, red as found: <ids> (each red
  when the run started)`. one red the run did not find red (a test the step
  turned red, one the run added, a flaky one), a count the names do not
  match, or an output with no summary to read keeps the fail.
- **red-test** - `marker` (default `FAILS:`) has to be in the output, or with
  `red: false` has to be gone from it. with `command: [...]` that is only the
  claim: the step names its test on a `TEST:` line, as a file or as
  `file::name` (whatever the command takes to run one test; only the part
  before `::` is looked for), the file has to exist in the run's `workdir`,
  and the command runs there with `{test}` replaced by the whole line. a line
  written as prose, `file - name` (any dash), `file, name`, `file :: name` or
  `name in file`, runs as `file::name`, and fails if the file defines no such
  name; a line that reads as none of these fails quoting it. a line of
  several ids, each `file::name`, runs them all, one argument each. a whole
  file named red that also holds tests the run started with runs as the ids
  of the tests the step added or changed in it, the pass naming them, and
  the step's `TEST:` line is handed on as those ids with a line saying what
  it named: a start test beside them is never handed to the next step as
  one it was given. a place with no start commit to read the file from runs
  the whole file. red
  passes on `expect` (default 1, a pytest run with a failing test) and on
  nothing else, so a test that passes, was never written, or was not
  collected is not red. red runs on the code as the run found it: while
  every product file is as the start snapshot hashed it, in the `workdir`;
  once a step has changed one (the code was written, then the test went
  back to be fixed), on a temporary checkout of the start commit holding
  the place as it started plus the run's test changes, and the pass says
  `on the start commit, without the product code written since`. a place
  with no start commit runs it in the `workdir`. `red: false` (or
  `"false"`, `no`, `0`) wants exit 0, in the `workdir`, and a step with no
  `TEST:` line of its own is held to the one the newest
  earlier step in the run named (red never borrows one: the step that says a
  test fails names it). a step that names the whole file an earlier step's
  ids are in is held to those ids. a `red` that is neither true nor false fails. without a command the pass
  says nothing was run. an empty answer fails as `the step answered nothing`,
  not as a test that never failed. a step held to `red: true` that cannot
  make a test fail (no `TEST:` and no `FAILS:` line, or each saying none) and
  asks a HANDOFF `QUESTION:` citing a `<file>:<line>` in the place parks the
  run on that question before this gate runs, `needs you: ruling`, with its
  `RECOMMEND:` as an option: no send-back is spent on it. a question that
  says none, or cites only `decisions.md` or the facts store, is no such
  question. one that asks nothing, says `TEST: none` and changed no file
  of the place, with no step before it in the leg changing one either,
  after an answer this run was given with `--answer` that is no
  `override:` (a `request:`, or a plain answer to its question), or after
  the flow's lead decided the question the step parked on here (read from
  the runner's own wording of it in the lead's entry), ends the run
  `stopped at <step>`, cause `no change`, outcome `done: no change`, exit
  0, in the leg it is in, with that ruling or decision as the reason: the
  request was answered and there is nothing to build. an `override:` never
  ends a run this way, an entry there when the run started is not its
  answer, and a step that writes no `TEST:` line at all is not read as
  saying none. otherwise the gate fails it as
  before. a run that skips tests never parks or ends this way.
- **red-first** - `command: [...]` with `{test}` in it, `expect` (default 1),
  `timeout`, `results` (`junit`, with `{results}` in the command). goes on
  the step that made the fix, and shows each new test fails without it and
  passes with it (below).
- **coverage** - a cobertura xml report, `report` (default `coverage.xml`, read
  in the run's `workdir`), held to a floor from `project.yml` (see
  `docs/orchestrate.md`). `floor` names which one, `overall` (default) or
  `critical`; `critical` needs `paths`, the file patterns it covers. it counts
  lines, not branches, and a line is covered if any copy of it in the report
  was hit. it runs nothing, so the command that writes the report goes in a
  command gate before it. no `project.yml`, or one with no number for the
  floor, is a failure and not a pass.
- **reject** - the `immediate_reject` rules in `project.yml` that carry a
  `pattern`, searched for in the output with `^` and `$` meaning a line, as in
  `regex`. a match
  fails the step and names the rule. it takes no options: a pattern written on
  the gate is refused. it reads what the step produced, not the working tree,
  so it belongs on a step whose output is the change. no `project.yml`, or one
  where no rule has a pattern, is a failure and not a pass.
- **project** - `name`, one of the `gates:` in `project.yml` (see
  `docs/orchestrate.md`), run as a command gate: in the run's `workdir`, with
  `{file}` replaced, passing on `expect` (default 0), `timeout`. the argv only
  comes from `project.yml`, so a `command` on the gate is refused. a name the
  file does not declare, or no `project.yml`, stops the run before any step is
  called. the detail starts with the name: `lint: exit 0`. `--skip project
  "<reason>"` skips every project gate in the run.
- **quote** - `source`, the step's input: a file or a folder, with `{INBOX}`,
  `{LOGS}` and `{WATCH}` read as a prompt reads them (`source: "{INBOX}"`).
  every span of the answer between double quotes, three words or more, has
  to be in one of its files word for word, spacing aside; the first one that
  is not fails the step, quoted. shorter spans are left alone, since two
  words are in almost any file. an answer that quotes nothing passes; one
  that quotes something from a source that resolves to nothing, or to a path
  that is not there, fails: nothing to check against is not a pass, and
  that fail is the gate's own (`broke`), so it caught nothing.
  the weekly digest's reviewer carries it, so a digest line quoting what no
  inbox file says goes back once and then stops the run.

the `project.yml` these gates read is `orchestrate/project.yml` in the run's
`workdir`, not in the directory agentweft was started from: a run with
`--workdir` on another repo reads that repo's file, and so does the fence
(`guardrails.md`). a project gate's name is checked against it once the
workdir is known, still before any step is called.

the run reads the file once, as it starts, and the gates and the fence hold
to that copy: a step that rewrites or deletes `project.yml` changes neither
the command its project gate runs nor the rules and numbers the reject and
coverage gates check. the copy is kept as `runs/<id>/project.yml`, and a run
picked up later holds to the copy its first leg read.

## each new test, without the fix and with it

    steps:
      - role: patcher
        prompt: patcher.md
        gates:
          - gate: red-first
            command: ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml={results}", "{test}"]
            results: junit

`red-test` shows a test failing at the time a step said it did. nothing in
that says the test is still the one that failed, or that it fails for want of
the fix, and a flow that commits nothing leaves no history for a reviewer to
read the order from. `red-first` runs it.

a run whose flow has a `red-first` gate writes down, as it starts, the commit
it started from, a sha256 of every test file in its `workdir` (tracked or
not, ignored ones left out) and the bytes of every file that already differed
from that commit (`agentweft/guardrails/snapshot.py`). after the step, a test
file whose content is not what it was is one the run wrote or changed; it
does not matter whether a step committed it. a test file is one under a test
path (`tests/`, `test/`, `spec/`, `__tests__/`) or named like one
(`test_x.py`, `x_test.py`, `x.test.ts`, `XTests.cs`), never one of the
runner's own `.md` files under `facts/` (`facts/tests/test_x.py.md` is the
store's, not a test). a python test in it is
new when its name was not in the file at the start or its code is not what it
was, and its id is the one pytest takes: `file::name`, `file::Class::name`,
nested classes included, a class counted when it is named `Test*` or derives
from a `...TestCase`. a python test module whose tests cannot be read from the
source (made at import time, or not parsing) is one id, the file. a file in
another language counts as one test when it is named like a test file
(`x.test.ts`, `XTests.cs`, `x_test.go`).

then `git worktree add --detach --lock` puts a checkout of the start commit
in a temp folder, with the repo's hooks switched off for it
(`core.hooksPath` pointed at an empty folder, so no post-checkout hook runs).
laid on it are the place's start state and the test files' changes, and
nothing else: the checkout holds what git tracks at the start commit, plus the
untracked files that are not ignored, so ignored files (a `.venv`, build
output, a local `.env`) and submodule contents are absent, and of the run's
own changes only the files under a test path or named like a test are there.
each new test runs there on its own and has to fail. an assertion is red, and
so is any other exception the unfixed code raises: a `KeyError` or a
`ZeroDivisionError` is the bug a crash fix removes. an `ImportError`,
`ModuleNotFoundError` or `NameError` is judged first on where it was raised,
the innermost frame of its traceback that is in the repo and not in an
installed package (`calc.py:2: NameError`, or `File "calc.py", line 2`). when
that frame is in a file that is not a test or the test runner's own, the
product raised it (a typo like `a + bb`, a broken import inside the product)
and it is red, whether or not the name it misses is in either tree. raised by
a test file, or with no frame in the repo, it is judged on what it misses,
read from its message (`cannot import name 'x'`, `No module named 'x'`, `name
'x' is not defined`):
- red when that module, or that name bound at module level (a `def`, a
  `class`, an assignment or an import), is not in the start tree and is in
  the place now: a feature's test fails on the name the feature adds
- an error when the name was there at the start or is not in the place now
  (a broken test, like a misspelt import), or the message names nothing

a `SyntaxError` or a collection error (pytest's exit 2) that is not one of
those is a test that could not run, which is not the same as catching the
bug. no step's `FAILS:` line changes either verdict. each then runs in the
place, with the fix, and has to pass; one that does not is failed with the
end of what it printed under it in `gates.md`, so the step sent back and the
person reading see why. both runs put the folder they run in,
and its `src/`, at the front of `PYTHONPATH`, so a project installed in
editable mode imports the tree being run and not the operator's fixed one.

without `results`, "on its own" is literal: one process per new test, once
without the fix and once with it, so 2N processes for N new tests. a command
that takes every id at once and writes a junit xml file can say so with
`results: junit` and `{results}` in the command (pytest's own
`--junitxml={results}` in the shipped flows): then `{test}` expands to every
new id and each side is one process. `{results}` becomes a path in a fresh
temp folder for each run, outside the place, so no file is left behind and
no file from an earlier run can be read. the outcome of each id is read from
that file and labelled by the rules above: a failure is red, or an error
when it is one of the could-not-run errors the fix does not explain; a
module that could not be collected gives every id in it the verdict a run of
that id alone would give. pytest stops a whole run on a collection error, so
when one is read, the ids it did not reach get one more batch. an id the file
does not settle (not in it, skipped, an error in setup, not a python id, or a
file that is missing or not xml) runs on its own, as without `results`: a
results file that cannot be read never reads as a pass. the one-test checks
elsewhere that take a red-first command (the supplied red test, the tests
left red) point `{results}` at a throwaway path. with `results`, red is a
failure in the file, not the `expect` exit.

the checkout is removed in a `finally`. it is locked while it exists, with
the run's pid as the reason, and the next run's start removes any that a
killed run left: named `agentweft-replay-*`, and unlocked or locked by a pid
that is no longer running. a replay a live run holds, a worktree the operator
locked, and every other worktree are left alone. the operator's checkout is
never stashed, checked out or reset.

a run started with `--worktree` (`docs/flows.md`) works in a worktree of its
own, and every gate here reads that one: the start snapshot is taken of it,
the replay's checkout is made from its start commit, and the changed-file
record is its diff. the tree the run was started from is not read or
written. that worktree is locked with the run's id as the reason, so the
start-of-run cleanup above never takes it for a replay a killed run left.

the assertion rule and the ids are pytest's. with another runner the gate
still runs each new test file as one id with `{test}`, red is the exit
`expect` names, green is exit 0, and exit 2 reads as could not run (pytest's
collection error). it cannot tell an assertion from an error in that runner's
output unless the output happens to read like pytest's, so there a red is the
`expect` exit and nothing finer.

the gate fails when no test was added or changed, when a new test errors
without the fix, does not run, or does not pass with it, when every new test
passes without the fix, and when a test a step named as `file::name` on a
`TEST:` line is one of those. a new test green both ways is a guard, kept and
named in the detail. the record is per test, in `steps.jsonl` (the gate's
`tests` list: `test`, `before` red / green / error, `kind` assertion or the
error's name, `after`, and on a red test `red_on`: `assertion`, `missing
name` when what it calls is not there yet (an `ImportError`,
`ModuleNotFoundError` or `NameError` red as above, or an `AttributeError`
on an attribute that is not in the start tree and is in the place now, and
never one on `None`, which is the code returning nothing), or `error` for
another exception the code raised) and in the handoff under "tests and checks", and the
steps after it are told what it ran: a verify step reads that the test failed
without the fix as a run, not as something it has to take on trust. so are the
red-test gate's own red runs, which happened before any later step started.

a case added after the fix is green is new test work, and is replayed the
same way. the run's red proof (below) keeps the new test ids there were when
a gate first showed the red, and every new id the replay finds beyond those
is one added after green. its record gets `added: "after green"` and
`counts`: `coverage` when it is red without the fix, `pin` when it passes
there. a pin pins current behaviour: it does not fail the gate, it is never
counted as coverage, and the gate's detail, `steps.jsonl` and the handoff's
test lines all name it (`...; added after green, pins current behaviour, not
counted as coverage`). the one exemption is a `PIN OK: <reason>` line from a
`planner`, `architect` or `ba` step, the steps that decide what is built: the
pins are then allowed, and the record keeps who said so and why (`pin_ok:
"planner: <reason>"`). a `PIN OK:` line from the step that wrote the case, or
any other, allows nothing. a proof that was carried in with `--continue`
keeps no ids, so a continued run's new tests are not split this way.

it shows the tests tell the fixed code from the unfixed, not that they are
good tests, and one run each way says nothing about a flaky test. a place
outside git, or a repo with no commit yet, has no start to replay from, and
the gate passes saying `not replayed` and why. a run picked up with `--resume`
replays from the snapshot the first run kept (`runs/<run-id>/start-snapshot.json`,
below), never from one taken at the pick-up, which would count the tests that
run wrote as already there. a run whose folder holds no snapshot passes saying
`not replayed - resumed, start state not kept`.

## no product code before a red test

    steps:
      - role: worker
        prompt: worker.md
        writes: tests
        gates:
          - gate: red-test
            red: true
            command: ["python", "-m", "pytest", "-q", "{test}"]
      - role: patcher
        prompt: patcher.md
        writes: product

a step says what it writes: `writes: tests`, `writes: product` or `writes:
none`. a flow with a `tests` or `product` step takes a start snapshot as the
run starts and keeps it as `runs/<run-id>/start-snapshot.json`: the start
commit, a sha256 of every spec file, of every test file and of every other
file (the product), plus the bytes of the files that already differed from
the start commit. content, never mtimes. a spec file is `TASK.md` or
`SPEC*.md` at the top of the place, or any file under `docs/spec*` there,
read from the place and not the top of the repo, and a `*` never crosses a
`/` (the handoff's rulings use the same definition). a project names its own
in `orchestrate/project.yml`, `spec: [docs/*.md, rules]` (a glob that names
a folder names every file under it), read once from the copy the run started
with; `AGENTWEFT_SPEC_GLOBS` (a comma list, `agentweft init` asks for it)
wins over both when it is set. a `spec:` entry that is absolute, climbs out
with `..`, or is empty stops the run before its first step. the test
runner's own files are in none of the three: `conftest.py` anywhere, `pytest.ini`,
`.coverage*`, and anything under `.hypothesis/` or `.pytest_cache/`. nor are
the runner's own files in the place, `decisions.md` and the `.md` files
under `facts/` (a test path inside it included), which it
writes between steps and between legs, and handoff.md never asks a ruling on
them as tests the run started with: a resumed leg never takes its own
counts for a change the run made. a place
outside git is hashed too, every file under it but those in a folder whose
name starts with a dot or is `__pycache__`, `node_modules`, `venv`, `.venv`,
`build`, `dist` or `target`; it has no start commit, so it has nothing to
replay, but its order still holds.

the checker holds the shape: once any step says what it writes, every step
has to, and every `writes: tests` step needs a red-test gate with `red: true`
and a command. that gate on the tests step is what gives the run its red
proof: it ran its command on a test file whose content is not what it was at
the start, and the test failed. a test the run started with and left as it
was counts too, the failing test a bug report ships with, once it is shown
red at the start and not only now: the tests step names it on its `TEST:`
line, the red-test gate runs it red, and then the runner runs it again in a
checkout of the start commit holding the place as it started (the files not
committed then included), with the flow's first red-test or red-first
command. there it has to fail on a test failing, by pytest's count: a setup
error such as a missing fixture, or a test that cannot even be collected, is
no proof. so is a supplied test made red by a `conftest.py`, a helper or
tooling the tests step wrote, since the checkout has none of them. a place
with no start commit has nothing to run it in, and gets no supplied proof.
the proof says which, `written` or `supplied`, and so does the handoff.
without a red-test gate that ran it there is still no proof. (a red-first
gate runs after the product step it sits on, so it can never let that same
step start, and it only counts tests the run wrote.) the proof is kept as
`runs/<run-id>/red-proof.json`. then:

- a `writes: product` step does not start until the run holds a red proof.
  the run stops `refused` before the step is called, and its why says so.
- a step that changes what its `writes:` does not name fails its `writes`
  check, which is a gate like the others: a `tests` step that changes
  product code or a spec file, a `product` step that changes a spec file
  (unless `spec_files: additions`, or a ruling quotes every spec line that
  moved), a `spec` step that changes a test or
  product code, a `none` step that changes anything. the step is sent back
  once with the files named, and the run stops `gate` if they are still
  changed. the tests, spec files and product files are hashed before the
  step's first go and again after each go, so a step sent back has to undo
  its edit, a commit changes nothing, and a step that a reviewer sends back
  after a later step ran is held to its own edits. a ruling the runner
  writes to `decisions.md` in between (the lead's decision on the step's
  question) is not the step's edit: the step is held to the file as the
  runner left it, and a change it makes there itself still fails, here and
  at the rulings check.
- anything unknown refuses: no start snapshot (a resume whose folder lost it
  stops with `no start snapshot`), no proof record, or a red-test gate that
  ran nothing.

two ways round it, both written into the run's `decisions.md` and the
handoff's "tests and checks":

- `--skip tests "<reason>"`, or `--skip-tests "<reason>"` for short, is a
  person deciding the run has no tests. a
  reason is required. then no test check applies at all: no order check, no
  `writes` check on a `tests` step, a `must_produce: "FAILS:"` is not asked for, and every
  `red-test` and `red-first` gate passes as `not run - tests skipped:
  <reason>`. a `command` gate that runs the whole suite still runs: it checks
  the product, not the order. the handoff's suite line says `tests skipped:
  <reason>`. a resumed run keeps it.
- `--continue <run>` carries the red proof an earlier run of the same place
  holds, as `tests carried from run <run>`, once each test file it proved is
  still the content it proved and that run's record holds (`verify <run>`):
  a proof changed after its run wrote it is not carried, `--force` or not.
  `--continue <commit>` carries the tests the
  start commit added or changed since that commit, plus the test files that
  were changed but not committed when the run started (`--continue HEAD`
  carries those alone), as `tests carried from <sha>`, once each is seen
  failing in the place as it starts, run one file at a time with the flow's
  first red-test or red-first command. a test file that did not exist at
  that commit and cannot even be collected (an `ImportError`, a
  `ModuleNotFoundError`, pytest's exit 2) counts as red: it is the usual red
  of a feature not written yet, and its kind is kept in the proof. nothing
  else is carried on trust: a moved test, a green one, or an older test file
  that could not run carries nothing and the run does not start.
- a red-first gate on the product step of a continued run that wrote no new
  test runs each carried test in the place with the fix; each has to pass,
  and the gate says `carried from <sha or run>, green with the fix`. each
  has to be byte for byte the file its red was shown on: a carried test the
  product step edited, or shadowed with a line of its own, fails. a run
  whose proof is a supplied test is held the same way: the gate says
  `supplied, red at the start, green with the fix`. a test such a run does
  add, the tests step's own included, is replayed as usual; when every one
  of them passes without the fix too, they are pins beside the given red
  (listed, never coverage), and the given tests still have to pass with
  the fix. a new test a step named on its `TEST:` line still has to be red
  without the fix. when some new test is red without the fix, the given
  tests are run with the fix too and each has to pass: a red that nothing
  fixed was not the bug the run fixed.

a run picked up with `--resume` keeps its snapshot and its proof, and reads
the proved tests again. the proof keeps each python test its red was shown
on (the ids the gate ran) by its syntax tree, with the code at the top of
its file that it reads and the other members of its test class, so a step
that changed other tests in the same file (start tests a test-edits park
then asks about) leaves the proof standing while the proving test is as it
was. a proved test whose own code, or code it reads in its file, changed,
one that is gone, or a file that no longer parses drops the proof, and so
does any change to a proved file read whole: a test file in another
language, a proof whose gate named only the file, a carried proof. a product
step after a dropped proof is refused saying which file moved.

## the tests the run started with, after product code

a test step can rewrite the assertion of a test it was given, and the product
step then makes the rewritten test pass: the place's own suite stays green and
nothing in it shows a test the run was handed now fails. so once a `writes:
product` step's gates pass, the run runs the tests it started with again, and
records it as a `start-tests` line in `gates.md`:

- which tests: the start commit's python test modules (`test_*.py`,
  `*_test.py`), plus the ones already loose when the run started, from the
  start snapshot. never the copies in the place, which a step may have
  edited; tests the run added are not among them.
- against what: a temporary checkout of the start commit (the same locked,
  hook-free one the red-first gate uses, gone afterwards), given the place's
  start state and then every product file as it is now, with the product
  files deleted since deleted there too. a step's commits change nothing: the
  start commit is the snapshot's, and the product is read from the files.
- a start test file every change of which the `test-edits` check below held
  under a ruling (an `override:` answer, or a WRONG TEST line quoting a line
  it covers) is laid out there as the run left it, after the product, so a
  test that runs it, such as a python test that runs a folder of js tests,
  is judged on the ruled file. a file with one change no ruling covers, or
  one that only gained tests, stays as the run found it.
- one pytest run over all of them, no model: the flow's red-test or red-first
  command up to `pytest` (else `python -m pytest`), with `-rA` and
  `--continue-on-collection-errors`. product files whose hashes are what they
  were at the start mean nothing is run, and so does a run with no python
  test module at the start.
- a test green when the run started and red now (failed, errored, or in a
  file that no longer collects) stops the run `stopped: spec conflict`, cause
  `conflict`, naming the test id and its assertion (`docs/journal.md`). which
  tests were green at the start is read from the suite baseline below, and
  only when something came back red: a test red at the start is never blamed
  on the run. every one red now on the same machine fault runs once more
  (above); held, it is the gate's issue and asks no question. the stop's one
  decision in the handoff is raised by `the start-tests check, after <the
  step>`: the check asks it, not the step.
- unless a ruling in `decisions.md` covers it: one that names the test (its
  id, with or without the folders before the file), or one that quotes in
  double quotes, three words or more, a line of a spec file as the run found
  it, in an entry that names the test, such as the answer to this stop. an
  answer of `request:` keeps the tests and covers nothing, and so does a
  decision of the flow's lead. covered tests pass as `red now, each covered
  by a ruling`.

a place outside git has no start commit and says `not replayed`. a checkout
that cannot be made, or a pytest that cannot start, fails the line like a
gate. with `--skip tests` it does not run.

## the tests the run started with, as it found them

the replay above catches a rewritten test once product code runs against it.
this catches the rewrite itself, at the step that made it, test step or
product step. after every step of a run that keeps a start snapshot (any flow
with a `writes: tests` or `writes: product` step or a `red-first` gate, or
with `spec_files:` or `baseline: on`), each test file the snapshot hashed is
read against how the run found it, and a changed one gets a `test-edits` line
in `gates.md`:

- python test files are compared per test function, by syntax tree, not by
  diff lines: a test the run started with that is gone (`removed`) or whose
  code is not what it was (`changed`) counts, and so does a change to the
  code its tests share, such as a constant or a fixture: a name the file had
  when the run started (a helper, a fixture, an imported name, a test) that
  is bound again further down to something else counts too, since every test
  using it now runs against the new binding though its own code is as it
  was (`the code its tests share changed`). so does code added that changes
  how those tests run: a `pytestmark` or `pytest_plugins`, a fixture with
  `autouse`, a statement that is not a definition or an assignment to plain
  names (a call, a module patched as the file loads), or a new name a test it
  started with reads or takes as a fixture. formatting and comments do not,
  and neither do other additions: a new name, on an import line of its own or
  added to one the file had, a constant or helper for the new tests, and a
  new test method in a test class the file had. a test the run started with
  whose only change is cases added to its `parametrize` list (the same
  argnames, keywords, arguments and body, every case it had still there; an
  `ids=` list may grow with the cases, one id per case, every case keeping
  its id) extends it and does not count either: it passes as `<file>: 0
  tests added,
  <id> extends by 1 case; no test the run started with lost or changed a line
  of its own`, and red-first replays it as a test whose code changed, on the
  start commit. a case changed or removed, or argnames changed, still counts.
  a file deleted counts for every test it held
  (`deleted with its file`).
- test files in other languages named like one (`*.test.ts`, `*Tests.cs`,
  `*_test.go`) are compared by line: one removed or rewritten counts. other
  files under a test folder are not read.
- a test added to a file the run found is the run's own and passes, as
  `<file>: 1 test added, none the run started with changed`; red-first
  proves it. handoff.md's rulings section reads the file the same way at the
  end of the run, so a python test file whose removed lines leave every test
  it started with and the code they share as they were (an import line that
  gained a name; nothing added that changes how they run) needs no ruling;
  a file already loose when the run began is not read that way and still
  does.
- a change fails the step like a gate, naming each test, and the step goes
  again with that at the end of its prompt. on its last go (the flow's
  `send_backs`, once by default) the run parks for a ruling instead, cause
  `parked`, with each test cited in `question.md`. it parks on the first go
  too when the step's other gates passed and a python test it changed is
  green as the run found it but red against the step's product now: put
  back, that test could only fail the suite, so the question comes before
  the send-back would leave the suite red. a changed test the product does
  not break still goes back first. two answers decide that
  park: `override:` (below), and one that says to put the tests back (`put
  them back`, `restore`, `revert`, `undo`, `as they were`), which sends the
  step again to do so. in a flow that names a lead, a `you decide` hands
  the pick between those two to the lead (above). any other answer, a
  `request:` included, decides nothing: the step would run again with the tests still
  changed and the check would park on them once more, so `--resume` takes
  no leg, prints the question with the two answers, and the run stays
  parked. the park is known by what the runner wrote in the leg's
  `manifest.json` (`stopped.runner.held`), never by the question's words; a
  lead question that cites a start test (above) keeps its own answers.
- unless a ruling in `decisions.md` covers the test: an `override:` answer to
  the question this run (or any leg before it) parked on for these edits
  covers every test and file that question cites. the runner knows that
  question by what it wrote in the leg's `manifest.json` when it parked
  (`stopped.runner`, its id and the tests it named), never by its words, so
  a step's own question written to look like it covers nothing. one that
  names the test (its id, or its name alone), or one that quotes in double
  quotes, three
  words or more, a line of a spec file as the run found it, in an entry that
  names the test, covers that test. so a test the run was handed with a wrong
  assertion can be fixed once a ruling quotes the spec line that decides it.
  an entry that only names the file covers nothing in it (a ruling on where
  a new case goes names the file too), and a change that is the file's own
  (the code its tests share, a file that no longer parses or cannot be read
  back) is covered only by the answer to its question. an answer of
  `request:` covers nothing, and neither does the flow's lead: it decides
  inside the tests it was given, so a decision of its that names the test
  still leaves the edit to the operator. covered tests pass as `changed, each
  covered by a ruling`, and handoff.md lists each test the override to this
  check's question covers as `<test> <- ruling <when> <heading> (named in the
  override to the test-edits question)`.
- or unless the run holds an override that lets the spec lines the test pins
  change, and an answer of this run names the test on a `WRONG TEST:` line
  whose `spec:` line quotes those lines, as the run found them or as the
  run's own ruled edit left them (`the quote` above; a range cite is read
  at the lines its quote stands on, as a CONFLICT cite is): the test was right
  about the old line and is wrong about the ruled one, so it may change with
  it. each line the claim quotes has to be one the run's edit removed or
  rewrote (a ruled line the run left as it was ties nothing: the spec was
  never moved), and the claim covers the test only when all three of these
  hold, each
  read from what the run found or what the tests do, never from what the
  step wrote into the spec or the test:
  - the test as the run found it, green at the start, is red against the
    product as it is now (the start-tests replay with nothing laid out as
    the run left it, read once per state of the product);
  - the test as the run left it is red against the product as the run found
    it (one pytest run of the start test modules the run changed, as it left
    them, in a checkout of the start commit with the start state, read once
    per state of the test files), so a rewrite that asserts nothing the old
    product fails (`assert listing([1])`) is not covered. this reads that the
    rewrite fails the old product, not that it pins anything: one that also
    reads a name or key the run added fails there too (see what no program
    here closes, below), and a module that no longer imports on the old
    product has no test result there, so each changed test in it is asked
    about. that is a floor too: an honest rewrite that widens its module's
    import to a name the run added is asked about, since reading the import
    error as red would pass a loosened test beside it in the module;
  - the test's code as the run found it shares a word with the quoted lines
    as the run found them: its names and string constants, and those of the
    code at the top of its file it reads (a constant, a helper, a fixture),
    so `item()["qty"]` reads `qty`; never a comment, a docstring or an assert
    message, and never a builtin name the code calls (`list(`, `next(`),
    while a string holding one (`item()["type"]`) counts. a quote of the
    ruled edit is read at the lines it stands in for as the run found them,
    and a line the run left as it was, moved by lines it added above, at
    that line; a quote of an added line ties nothing.
  a test file read by line (a js test file) has no test id the replay can
  run, so a claim on it, or on a test in it, covers the file when the start
  tests turn instead: a python start test the product now leaves red (a
  test that runs the js suite) is green in a second start-tests replay with
  every file read by line the answers claim under a ruling laid out as the
  run left it, stays red in a third with all of them but this file, and is
  red on the start state with this file alone as left, every other start
  file as found (the file as left needs the run's product: an emptied or
  loosened file is green there, beside another claimed file or not), and
  the file's code as the run found it shares a word with the quoted lines
  as the run found them: the names and string literals of the whole file,
  never a comment, a test title (the first string of `describe(`, `it(`,
  `test(`), a keyword or a test runner name (`expect`, `toEqual`). these
  are the three conditions a python claim meets, read per file, with a wider
  word read: it also counts import paths (`require('./list')`, `from
  './list'`), js globals (`Object`, `Set`, `Map`, `JSON`, `Math`) and an
  assertion's message string, where the python read cuts builtins and a bare
  `assert`'s message and reads no import line. an unclaimed file is
  never laid out, and a claimed file that shares no word, that the turn
  does not need, or whose layout turns no python test, is asked about. the turn reads the file whole: an unclaimed loosened line in a
  claimed file rides with it when the turn still goes green. a claim does
  not cover a test the replay does not reach (one that reads the spec
  files, which the replay lays out as the run found them, or any test in a
  run that skips tests). a claim
  quoting a ruled line for a test that pins something else covers nothing.
  a test changed with no such line, or quoting a line no ruling covers,
  still fails, and on its last go parks on this check's question, which an
  `override:` to it answers for every test it names. the floor, what no
  program here closes: a claimed test whose found code shares a word with a ruled line
  the run rewrote, that the product now breaks (the ruled change, or a
  behaviour no ruling covers that the step broke too), is covered once the
  step rewrites it to anything the old product fails; reading a name or a
  key the run added is enough, so the rewrite need not pin the broken
  behaviour, or anything. for a file read by line the same holds per file:
  its found code shares a word with the line, a python test that runs it
  goes red with the run's product and needs the file as left to turn green,
  and the file as left, alone, fails the old product; a read of a new key
  is enough there too, and the word may sit anywhere in the file, since
  the file is read whole. no program tells such a read from a pin, since an
  honest rewrite fails the old product the same way (a missing key). the
  product diff, the typed claim and the start-tests line naming the test
  show it. the
  code a python file's tests share counts only when each
  test the file started with that reads what changed, itself or through a
  helper it calls, is named that way; every test it started with, when the
  change is a fixture with autouse, a name pytest reads, a call as the file
  loads or a member of a test class. a file read by line counts when a test
  in it is. a test removed, a file
  deleted or one that no longer parses never does. the step that fails this
  check under such an override is told the `WRONG TEST:` way too, and
  handoff.md's rulings section lists each test under the ruling with the
  line its claim quoted, `<file> +a -d: <test> <- ruling <when> <heading>
  (claimed on <file>:<line>)`.
- a start test changed with no claim is never listed under a ruling by the
  run alone, however much its change looks like the ruled edit's: it fails,
  and on the last go parks on this check's question, one question naming
  every such test. the question carries what the run found, as evidence for
  the operator that decides nothing: each python test is `red as found` or
  `green as found` against the product now, `reads <word> of <file>:<n>
  (ruled)` when its code as the run found it shares a word with a spec line
  a ruling lets change and the run's edit rewrote, and `rewrite red on the
  start product` when the test as left fails the product as found; a file
  read by line is `file read whole`. with more than one test the question
  counts them by group (`73 red as found and reading a ruled line, 7 red as
  found, 7 green as found, 19 changed whole (a file or the code its tests
  share)`). an `override:` to it covers every test it names.

which files changed is read from content hashes, and what they held from the
start commit (or the snapshot, for a file already loose), so a step that
commits its edit, or commits the file's deletion, is read the same as one
that leaves it in the work tree. a place with no start commit has only the
hashes, so a test file the run found that changed there is held as changed
(nothing can show the change was only an addition) until the answer to its
question rules it.

## the suite as the run found it

    # flow.yaml
    baseline: on

the same start tests, run on the start state alone: a temporary checkout of
the start commit given the files that were already loose, no product change,
one pytest run, no model. what each test did is kept as
`runs/<id>/baseline.json`: the start commit, the dirty-tree id, the passed
tests, the red ones with what they said, the flaky ones, and `from: run` or
`from: cache`.

- when: `baseline: on` runs it as the run starts; `auto`, the default, only
  when it is needed, which is once the start-tests replay comes back red or a
  stop finds a test the run added or changed red; `off` never, and then the
  replay runs the start state for itself and nothing is kept.
- cached by what decides it: the start commit, a hash of the files loose at
  the start (none for a clean tree), the command that starts pytest, the
  python version and the lock files at the start. the cache is a
  `baseline-<key>.json` under the runs root, so a second run on the same
  commit reads it and runs nothing.
- a test red at the start is run again alone, up to three times, in the same
  checkout. one that passes on a retry is flaky: it is not read as green at
  the start, so it is never blamed on the run either.
- the handoff's tests section names each one: `red when the run started, not
  the run's doing: <id>: <what it said>` and `flaky when the run started (red,
  then green on a retry): <id>`. a test left red by a stop that was already
  red at the start says `red when the run started` after it.

a place outside git, or with no commit, has no start state to run and keeps
no baseline; neither does a run with `--skip-tests`.

## a rule is checked only if it has a pattern

    standards:
      immediate_reject:
        - "business logic in an endpoint"
        - rule: "a debugger left in"
          pattern: 'breakpoint\(\)|pdb\.set_trace\('

the first is a sentence and stays one: no pattern means it, so it is still only
asked for. the second is the same kind of rule with a program behind it, and
the gate passes saying how many rules it checked and how many it could only
ask for, so the split stays visible.

## the number is not in the flow

    gates:
      - gate: command
        command: ["python", "-m", "pytest", "-q", "--cov", "--cov-report=xml"]
      - gate: coverage
      - gate: coverage
        floor: critical
        paths: ["billing/*"]

the flow says which report and which floor. what the floor IS comes from
`coverage:` in `project.yml`, and a number written on the gate is refused.
test-qa used to carry it as a sentence, where it could be read, agreed with and
then not met. it is a check now.

## the command is not in the flow either

    gates:
      - gate: project
        name: lint

a project gate goes on the step whose work it checks, like every other gate,
and runs once that step is done. the flow says which one and where; what it
runs is `gates: lint:` in `project.yml`, so one codebase's linter is not
written into a flow every codebase shares.

## why command matters

anything with a cli is a check now, without me writing an adapter. a linter, a
spell checker, a test runner, something that does not exist yet. the gate does
not know or care what it is - it looks at the exit code.

that is the whole extension point of this repo. if you want a check i have not
thought of, you do not write a plugin, you write a program.

`examples/tare-gate` is the one you can run: tare checks a written-up
draft for claims nobody sourced, and its exit codes already say passed, could
not run and refused (0, 1, 2), so the gate is a `command:` line and nothing
else.

fix-with-test is where it earns it. the closing step used to be a model reading
its own patch and saying the test passes now; it is `python -m pytest -q` and
an exit code on the patcher, and a non-zero one sends the step back once, then
stops the run. a `red: false`
gate runs the test the patcher names, or the worker's when it names none, and
a `red-first` gate replays each new test without the patch, the cases the
patcher adds after the fix included.

that is every promise the flow makes, and each one is a program, so its verify
judge is off (`verify: off`). the judge used to be asked three things: that the
test failed on the unpatched code, which the gates above now run; that the
whole suite passed, which the `command` gate runs; and that the test was
written before the patch, which nothing in a working tree can show, so it is
no longer asked. on real fixes it caught nothing the suite did not, and it
failed correct fixes on the order question, most often over the extra cases a
patcher is told to add once it is green. `python run.py show fix-with-test`
prints each promise with the gate that shows it.

`verify: judge` puts it back for the one thing no program here shows: whether
the patch is the smallest one. it is asked that and nothing else, through
`verdict`, and an answer it is unsure of is recorded as unproven, not as a
pass. the run then ends `done, 1 check unproven` and says which.

## the short suite or the long one

    context:
      command: ["some-tool", "mcp"]
      tool: hotspots
      arguments: {dir: "."}
    steps:
      - role: patcher
        prompt: patcher.md
        gates:
          - gate: command
            command: ["python", "-m", "pytest", "-q"]
            cold:
              command: ["python", "-m", "pytest", "-q", "-m", "not slow"]
              threshold: 0.7

`command` is the long one. the files the step names are checked against the
ranking the `context:` block brought back (see `docs/mcp.md`), the same way
preflight checks them: when it names at least one and none is at `threshold`
(default 0.7), `cold`'s command runs instead. one hot file and the long one
runs. so does a run with no ranking - the server was down, the flow has no
`context:`, the step ran before the planner fetched it, or the run was picked
up past the planner with `--resume` - and a step that names no file at all, because none of those says the change
is small. `expect` and `{file}` mean the same for both commands, and the
result says which one ran and why.

it reads the files the step SAYS it touched, not the diff, so a step that
edits a hot file without naming it gets the short suite.
