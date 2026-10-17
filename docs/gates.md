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
them. a `NEEDS:` whose `SIZE:` changes no code, that carries a
`RECOMMEND:` and cites no spec line (`CITES:`) does not park at all: it
becomes a doubt and the gates run as on
any answer (`docs/journal.md`, when a step asks for a ruling). so does a `WRONG TEST:`
answer, which sends a test the run wrote back to the step that wrote it, to be
shown red again by that step's gates, or parks on one the run started with.

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
words>` on the line after it, is read first. when the quote is at that line as the run found it, the run stops on
cause `conflict` before any gate runs, so a red test the step marked as
contradicting the spec is never something the step is sent back to turn
green. when it is not, a `conflict` result goes in front of the step's gates
and fails it, with what was wrong (`docs/journal.md`, when the request
contradicts the spec).

the same holds for every other quote a step gives as evidence. a `REFUSED:`
line and the `spec:` line under a `WRONG TEST:` claim that cite a line that
is there have to quote what that line says as the run found it; when they do
not, the refusal does not end the run and the claim goes to no one: a `quote`
result goes in front of the step's gates and fails it, naming the quote and
the line (`the WRONG TEST spec: line quotes "...", which is not at
TASK.md:3 as the run found it`), and the step is sent back as for any gate.
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
printed, not the first: a test runner says what failed at the end.

a command, red-test or red-first gate runs its command with
`PYTHONDONTWRITEBYTECODE=1` and `PYTHONPYCACHEPREFIX` set to a new empty
folder, so python neither leaves bytecode in the place nor runs the bytecode
an earlier run left: a `.pyc` is trusted on the source's size and its mtime in
whole seconds, and an edit of the same size within the same second would
otherwise run the old code.

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
  program), fails the gate and says so; it is not a tool fault.
- **red-test** - `marker` (default `FAILS:`) has to be in the output, or with
  `red: false` has to be gone from it. with `command: [...]` that is only the
  claim: the step names its test on a `TEST:` line, as a file or as
  `file::name` (whatever the command takes to run one test; only the part
  before `::` is looked for), the file has to exist in the run's `workdir`,
  and the command runs there with `{test}` replaced by the whole line. a line
  written as prose, `file - name` (any dash), `file, name`, `file :: name` or
  `name in file`, runs as `file::name`, and fails if the file defines no such
  name; a line that reads as none of these fails quoting it. red
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
  test fails names it). a `red` that is neither true nor false fails. without a command the pass
  says nothing was run. an empty answer fails as `the step answered nothing`,
  not as a test that never failed.
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
(`test_x.py`, `x_test.py`, `x.test.ts`, `XTests.cs`). a python test in it is
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
place, with the fix, and has to pass. both runs put the folder they run in,
and its `src/`, at the front of `PYTHONPATH`, so a project installed in
editable mode imports the tree being run and not the person's fixed one.

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
that is no longer running. a replay a live run holds, a worktree a person
locked, and every other worktree are left alone. the person's checkout is
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
error's name, `after`) and in the handoff under "tests and checks", and the
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
`/` (the handoff's rulings use the same definition). the test runner's own
files are in none of the three: `conftest.py` anywhere, `pytest.ini`,
`.coverage*`, and anything under `.hypothesis/` or `.pytest_cache/`. a place
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
  after a later step ran is held to its own edits.
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
the proved test files again: one whose content is not what was proved drops
the proof, and a product step after it is refused saying which file moved.

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
  on the run.
- unless a ruling in `decisions.md` covers it: one that names the test (its
  id, with or without the folders before the file), or one that quotes in
  double quotes, three words or more, a line of a spec file as the run found
  it, in an entry that names the test, such as the answer to this stop. an
  answer of `request:` keeps the tests and covers nothing. covered tests pass
  as `red now, each covered by a ruling`.

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
  code its tests share, such as a constant or a fixture. formatting,
  comments and imports do not. a file deleted counts for every test it held
  (`deleted with its file`).
- test files in other languages named like one (`*.test.ts`, `*Tests.cs`,
  `*_test.go`) are compared by line: one removed or rewritten counts. other
  files under a test folder are not read.
- a test added to a file the run found is the run's own and passes, as
  `<file>: 1 test added, none the run started with changed`; red-first
  proves it.
- a change fails the step like a gate, naming each test, and the step goes
  again with that at the end of its prompt. on its last go (the flow's
  `send_backs`, once by default) the run parks for a ruling instead, cause
  `parked`, with each test cited in `question.md`.
- unless a ruling in `decisions.md` covers the test: an `override:` answer to
  the question this run (or the leg it picked up) parked on for these edits
  covers every test and file that question cites; one that names the test
  (its id, or its name alone), or one that quotes in double quotes, three
  words or more, a line of a spec file as the run found it, in an entry that
  names the test, covers that test. so a test the run was handed with a wrong
  assertion can be fixed once a ruling quotes the spec line that decides it.
  an entry that only names the file covers nothing in it (a ruling on where
  a new case goes names the file too), and a change that is the file's own
  (the code its tests share, a file that no longer parses or cannot be read
  back) is covered only by the answer to its question. an answer of
  `request:` covers nothing. covered tests pass as `changed, each covered by
  a ruling`.

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
`context:`, the step ran before the planner fetched it, the run was picked up
past the planner with `--resume`, or it is an eval run, which fetches none -
and a step that names no file at all, because none of those says the change
is small. `expect` and `{file}` mean the same for both commands, and the
result says which one ran and why.

it reads the files the step SAYS it touched, not the diff, so a step that
edits a hot file without naming it gets the short suite.
