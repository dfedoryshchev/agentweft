# writing a new flow

copy `flows/_template` and rename it. that is most of it.

    cp -r flows/_template flows/my-flow

it is three files, not six. `planner`, `reviewer` and `verify` come from
`roles/library/`, so a flow only writes a role file when it has something to
say that the role does not already say everywhere else.

## 1. say what it is for, in one line

put it at the top of `instructions.md`. if you cannot write that line the flow
is not ready to exist yet. every flow i have deleted failed this test first and
i ignored it.

## 2. write the planner before the worker

the planner reads and decides, the worker does. the temptation is to skip the
planner for a small flow, and every time i have done that the worker starts in
the middle of the input and never recovers.

## 3. keep the shared rules out

do not put "markdown only" in your role prompts. it is already in
`fragments/`. do not write the verdict block into your reviewer either; that
is in `roles/library/reviewer.md` and it gets appended for you. only put rules
in `instructions.md` that are true for this flow and not for the others.

a test fails if a flow prompt repeats a line the library already says, which
is there because i pasted that block into five files before writing this
sentence.

## 4. give the reviewer something to disagree with

a reviewer that just reads nicely written output agrees with it. the ops-check
reviewer works because its prompt lists the specific things that are NOT
findings. be that specific or skip the reviewer.

## 5. a flow that changes code needs a program to say it worked

two shipped flows change code, and both put the check in a gate, not in a
prompt. `fix-with-test` fixes a bug. `build-feature` builds one from a spec:

    python run.py build-feature --workdir ../my-project --task "calc gets mul(a, b)"
    python run.py build-feature --workdir ../my-project --task-file spec.md

- the planner turns the spec into behaviours a test can check
- the tester writes the failing tests and nothing else. a `red-test` gate runs
  the file it names and wants pytest's exit 1, so a test that already passes,
  or a file pytest cannot even import (exit 2), stops the run before any code
  is written
- the worker writes the code, and a `command` gate runs the whole suite and
  wants exit 0. a `red-first` gate then runs each new test without the code
  (a temporary checkout of the start commit plus the test files) and with it:
  red then green, test by test, or the run stops. the tester's `FAILS:` line
  naming an `ImportError` is what lets a test that fails on the missing name
  count as red (`docs/gates.md`)
- one reviewer, `on_redo: worker`, sends the code back, not the tests

the suite is `python -m pytest -q`, written in its `flow.yaml`. a project
that runs its tests some other way changes that line in a copy of the flow.

each step says what it writes, and the runner holds the order rather than the
prompt:

    - role: tester
      writes: tests
    - role: worker
      writes: product

`writes: tests | product | none`. a `product` step does not start until a
red-test or red-first gate in this run has seen a test the run wrote fail; a
`tests` step that changes any file other than a test or spec file fails.
`--skip-tests "<reason>"` runs without tests and says so; `--continue <run or
commit>` carries tests already written. the rules are in `docs/gates.md`, "no
product code before a red test".

## 6. run it three times before you trust it

    python run.py my-flow --force

the first run tells you the prompt is wrong. the second tells you the output
shape is wrong. the third is the first one worth reading.
