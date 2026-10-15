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
- the tester writes the failing tests, one per planned behaviour, and nothing
  else: no boundaries, callers or error paths around them yet. a `red-test` gate runs
  the file it names and wants pytest's exit 1, so a test that already passes,
  or a file pytest cannot even import (exit 2), stops the run before any code
  is written
- the worker writes the code, and once the given tests are green it adds the
  cases around the change (`fragments/tests.md`). a `command` gate runs the
  whole suite and wants exit 0. a `red-first` gate then runs each new test
  without the code
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

`writes: tests | product | none`, on every step once one says it. a
`product` step does not start until the red-test gate (`red: true` and a
command, which every `tests` step needs) has seen a test the run wrote fail;
a `tests` step that changes any file other than a test, a spec or a test
runner file is sent back once, then the run stops. `--skip-tests "<reason>"`
runs without tests and says so; `--continue <run or commit>` carries tests
already written, committed or not. the rules are in `docs/gates.md`, "no
product code before a red test".

`fix-with-test` is the same shape with one step fewer: the worker's `red-test`
gate wants the new test red, and the patcher's gates want it green, replay
each new test without the patch (`red-first`) and run the whole suite
(`command`). a promise you write should be one of those: "the new test fails on
the unpatched code" is a gate, "the test is written before the patch" is a
sentence a model is asked to agree with. `python run.py show <flow>` prints
each promise with the gate that shows it, and one with none beside it is only
asked for.

when every promise is a program, a judge at the end has nothing left to check
and a way to fail correct work, so `verify:` at the top of the flow switches it:

    verify: "off"     # the verify steps are declared and not run
    verify: judge     # they run as written

`fix-with-test` ships `verify: "off"`, with its verify step left in the file
asking only whether the patch is the smallest one, the one thing no program
there shows. a flow that does not say runs its verify steps as written.
`verify: judge` with no step of role `verify` is refused when the flow loads.
quote the `"off"`: unquoted, yaml reads it as false, which is read as off too,
but anything that reads the file without the loader sees `false`.

## 6. say how many times the work can go back

a reviewer's `VERDICT: redo` sends the work back, and so does a failed gate.
both stop somewhere and hand the run to you, and `send_backs` in `flow.yaml`
says where:

    send_backs: 3

it is a whole number, 0 or more, and anything else is refused when the flow
loads. it counts two things. a verdict's trips are counted for the whole run,
and a failed gate's per step, so a gate failing on one step never spends
another step's goes. leave it out and a verdict sends the work back twice and
a gate once, which is how every shipped flow runs. the stop says which cap it
hit and its value: `the work has gone back 3 times already (send_backs: 3)`.

the verdicts a step may give are the `VERDICT:` lines its file lists, and an
answer outside them fails the step. a judge that should be able to say the
request is really a change to the spec gets one more line in its file:

    VERDICT: spec change request

answered, it parks the run for a ruling with the judge's reason, the lines
after the verdict, instead of sending anything back.

## 7. say who decides first

a step that cannot go on without a decision asks with a `NEEDS:` line, and the
run parks for you. `lead` names a step that is asked first:

    lead: planner

it is a step or a role of the flow (a role means its first step), or `none`,
which is the same as leaving it out. a fanned-out step cannot lead, and a name
that is no step is refused when the flow loads. the lead decides with
`DECIDED: <option>` and a `why:` line under it, and the step that asked runs
again with the decision; anything that would change the spec or a test the
run started with, an `ESCALATE:`, or a second ask of the same question comes
to you. pick the step that already reads the spec for the whole flow:
build-feature leads with its planner, and fix-with-test, whose first step
writes the test, has `lead: none`. how it reads in a run is in
[the journal](journal.md#when-a-step-asks-for-a-ruling).

## 8. run it three times before you trust it

    python run.py my-flow --force

the first run tells you the prompt is wrong. the second tells you the output
shape is wrong. the third is the first one worth reading.
