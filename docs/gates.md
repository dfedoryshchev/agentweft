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

a step with no gates gets its heading in `gates.md` too, with `no gates`
under it, and its line in `steps.jsonl` says `"ungated": true` (see
`docs/journal.md`). without it, a step missing from `gates.md` could have
had no gates or never got as far as the check, and the file could not say
which.

a gate reads the answer without its HANDOFF block (`journal.md`, "what each
step hands over"): the block is the step's account of the work, and a length
cap or a pattern is about the work.

a gate name that is not one of the eight below, or an option the gate does not
read, is refused when the flow loads, before any step is paid for.

## the eight

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
  the run's end line: a run that got through every step with one reads
  `done, 1 check unproven` where a clean one reads `finished`. the end line is
  built by `outcome` in `agentweft/runner/summary.py`.
- **length** - `max_lines`, `min_lines`.
- **command** - `command: [...]`, with `{file}` replaced by a temp file holding
  the output. passes when the exit code matches `expect` (default 0). it runs
  in the run's `workdir` (see `docs/flows.md`), so it can check the work
  itself and not only what the step said about it. a `cold:` block gives it
  a shorter command for a change the risk map says is small (below).
- **red-test** - `marker` (default `FAILS:`) has to be in the output, or with
  `red: false` has to be gone from it. with `command: [...]` that is only the
  claim: the step names its test on a `TEST:` line, as a file or as
  `file::name` (whatever the command takes to run one test; only the part
  before `::` is looked for), the file has to exist in the run's `workdir`,
  and the command runs there with `{test}` replaced by the whole line. red
  passes on `expect` (default 1, a pytest run with a failing test) and on
  nothing else, so a test that passes, was never written, or was not
  collected is not red. `red: false` (or `"false"`, `no`, `0`) wants exit 0,
  and a step with no `TEST:` line of its own is held to the one the newest
  earlier step in the run named (red never borrows one: the step that says a
  test fails names it). a `red` that is neither true nor false fails. without a command the pass
  says nothing was run. an empty answer fails as `the step answered nothing`,
  not as a test that never failed.
- **red-first** - `command: [...]` with `{test}` in it, `expect` (default 1),
  `timeout`. goes on the step that made the fix, and shows each new test
  fails without it and passes with it (below).
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

## each new test, without the fix and with it

    steps:
      - role: patcher
        prompt: patcher.md
        gates:
          - gate: red-first
            command: ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "{test}"]

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
`ModuleNotFoundError`, `NameError` or `SyntaxError`, or a collection error
(pytest's exit 2), is a test that could not run, which is not the same as
catching the bug, unless the red step's `FAILS:` line names that error: a
feature's test fails on the name the feature adds. the step that made the fix
cannot declare it for itself. each then runs in the place, with the fix, and
has to pass. both runs put the folder they run in, and its `src/`, at the
front of `PYTHONPATH`, so a project installed in editable mode imports the
tree being run and not the person's fixed one.

the checkout is removed in a `finally`. it is locked while it exists, with
the run's pid as the reason, and the next run's start removes any that a
killed run left: named `agentweft-replay-*`, and unlocked or locked by a pid
that is no longer running. a replay a live run holds, a worktree a person
locked, and every other worktree are left alone. the person's checkout is
never stashed, checked out or reset.

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

it shows the tests tell the fixed code from the unfixed, not that they are
good tests, and one run each way says nothing about a flaky test. a place
outside git, or a repo with no commit yet, has no start to replay from, and
the gate passes saying `not replayed` and why. so does a run picked up with
`--resume` (`not replayed - resumed, start state not kept`, in "tests and
checks"): the first run's start state is not kept, and a snapshot taken at
the pick-up would count the tests that run wrote as already there.

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
an exit code, and a non-zero one stops the run. a `red: false` gate runs the
test the patcher names, or the worker's when it names none, a `red-first`
gate replays each new test without the patch, and the verify answer goes
through `verdict` with `passes: 3`, one for each thing it is asked to check. a
check it answers unsure does not stop a fix the programs proved; the run ends
`done, 1 check unproven` and says which.

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
