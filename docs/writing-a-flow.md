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

keep out what a gate already holds, too: that the test file is run after the
step answers, that a misquoted spec line fails the answer, that a case added
after green is shown red or reported as a pin. the gate does it whatever the
prompt says, and its refusal tells the step when it matters. a line goes only
once a test shows the gate firing on the shipped flow, and a line that coaches
(how to make the test fail, why to write the conflict) stays even when a gate
checks the outcome. `tests/test_prompts.py` holds the lines taken out so far.

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
  red then green, test by test, or the run stops. a test that fails without
  the code on an `ImportError` for a name the code adds, or on an import or
  name error the code itself raises, counts as red, the worker's own cases
  included (`docs/gates.md`)
- two reviewers, each `on_redo: worker`, send the code back, not the tests.
  the first reads the change against the spec and the tests, the second runs
  the new code on what the tests leave out and holds it to the project's own
  way: the facts handed for its files (`docs/journal.md`), the spec's layout
  and rules, and how the code beside it already does the same thing. a change
  done a way those rule out is a redo, with a `CONVENTION:` line quoting the
  fact or the `file:line` it goes against. a redo from either sends the work
  back, and it comes past both again
- the first reviewer also names, under its verdict, one wrong implementation
  the tests would let pass and the case that fails it. with `on_missed:
  tester` an ok sends that case to the tester, once a run, which adds it, and
  the worker and both reviewers go again behind it. when the suite already
  passes with the case in, the worker does not go again and the second
  reviewer takes the work (`docs/journal.md`)

a second reviewer is a second lens, not a second opinion. when a flow runs
more than one reviewer, each says in `lens:` the one line it reads for, no
two say the same, and each is told its own line and the others'. the next
reviewer is handed the work the first one was, not its verdict, in a run
and in a scored eval case alike.
`reviewers: <n>` runs the first n of them, so `reviewers: 1` in a copy of the
flow runs build-feature with the spec reviewer alone:

    - role: reviewer
      prompt: reviewer-runs.md
      on_redo: worker
      lens: "what the tests do not run, and the project's own way: ..."
    reviewers: 2
    small_reviewers: 2

`small_reviewers: <n>` is how many of those run on a change the runner sizes
small. before the first reviewer it reads the change from git, since the run
started, and sizes it with no model (`agentweft/mcp/preflight.py`): its blast
is high when it touches a file the risk map the planner was handed ranks hot,
sets a key in a config file, changes any line of a dependency or build
manifest (`requirements*.txt`, `pyproject.toml`, `package.json`, a lock file,
a `Dockerfile`, a `Makefile`), or adds a command-line flag, however few lines
that is. with no risk map (a flow without `context:`, or a server that gave
none) the blast is unknown, never low, so the change is not small. its logic
lines count code only, the lines a deleted file took out with them, so a
long locale, data or docs file adds none. a change is small with a low
blast, at most 20 logic lines in at most 2 code files and at most one new
public name. a run prints the size as it sizes it and each reviewer it
leaves out, a scored eval run too, and the handoff says the size and why
under "tests and checks", and each reviewer it left out. build-feature
ships with 2, so a small change still gets both; `small_reviewers: 1` in a
copy runs the spec reviewer alone on one. a place outside git is not sized,
and every reviewer runs.

the suite is `python -m pytest -q`, written in its `flow.yaml`. a project
that runs its tests some other way changes that line in a copy of the flow.

the `command` gate that runs the whole suite and wants exit 0 may run it in
parallel, `python -m pytest -q -n auto`, where the project has pytest-xdist
installed: it reads only the exit code, and xdist keeps 0 for a green suite.
the commands with `{test}` in them, the `red-test` and
`red-first` gates, stay without it. they run one test, or a few, and read the
exit code to tell a red test from one that could not run: pytest says 2 for a
test file it cannot import, and under `-n` the same file says 1, the exit of a
red test.

each step says what it writes, and the runner holds the order rather than the
prompt:

    - role: tester
      writes: tests
    - role: worker
      writes: product

`writes:` is one of `tests`, `product`, `spec` or `none`, on every step once
one says it. a `product` step does not start until the red-test gate (`red:
true` and a command, which every `tests` step needs) has seen a test the run
wrote fail. each step is held to what it said: a `tests` step that changes
product code or a spec file, a `product` step that changes a spec file
(unless `spec_files: additions`, or a ruling quotes every line it moved), a
`spec` step that changes anything but a spec file, or a `none` step that
changes anything is sent back once, then the run stops. `--skip-tests "<reason>"` (short for `--skip tests
"<reason>"`) runs without tests and says so; `--continue <run or commit>`
carries tests already written, committed or not. the rules are in `docs/gates.md`, "no
product code before a red test".

a test that was red before the run touched anything is not the run's doing,
and `baseline:` says when the runner finds those out:

    baseline: auto    # once a test comes back red (the default)
    baseline: "on"    # as the run starts
    baseline: "off"   # never

it runs the start tests on the start state, keeps what each did in
`runs/<id>/baseline.json`, and caches it by start commit under the runs root,
so a second run on the same commit runs nothing. a red test is run again up
to three times and one that turns green is called flaky. the handoff names a
test red at the start as `red when the run started`. as with `verify:`, an
unquoted `on` or `off` is read as true or false, which the loader reads as on
and off (`docs/gates.md`, "the suite as the run found it").

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

some repos must never get a commit nobody typed, so a run commits nothing
unless the flow says so:

    commits: none     # never commit (the default)
    commits: wip      # commit after each step, on a branch of the run's own
    commits: squash   # that, then one commit for the task at the end

`AGENTWEFT_COMMITS` sets the mode for a flow that names none, and anything
but those three words is refused. a resume refuses a mode other than the one
the run started with.

`wip` and `squash` start the run on `agentweft/<run id>`, never the branch you
started it on, and nothing is ever pushed. a commit holds what the run
changed: a file already loose when the run started stays out while its bytes
are what they were, and so does a change you had staged. a file you had
changed that a step then changes, or one you edit while the run goes on, is
committed whole, your edits with the run's. no hook of the repo's runs for the
run's git commands, and with `commit.gpgsign` on, a signer that cannot sign
refuses the run before its first step. the commits are authored as git
config's `user.name` and `user.email` in the place, and with either missing
the run refuses before its first step. so it does with a merge, cherry-pick,
revert or rebase in progress there, which switching to the run's branch would
drop. every gate reads the files by content from the start snapshot, so a flow
gives the same verdict in all three modes; the commits add the order they were
made in to the handoff (`docs/journal.md`, "the run's own commits").

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

## 7. let a step that goes again carry its own session on

a step sent back starts from nothing by default: its whole prompt again, and
every file it read, read again. `continue:` on a step says otherwise:

    - role: worker
      prompt: worker.md
      continue: resume

- `fresh` (the default) asks the step with its whole prompt every time.
- `resume` carries the step's own session from its last call in the run on:
  the call after the first is sent only what is new since its last answer
  (the send-back, the failed gate, the lead's question or decision), and
  what it read before comes from the cache.

each call is a copy of the session before it (`claude --resume <id>
--fork-session`), never the session itself, so a call that fails goes again
from the same point. the id of every session is chosen before its call
(`--session-id`) and kept in the run's `manifest.json` under `sessions`, so
`--resume` of a run that stopped carries the step's session on too. the run
is charged only what the call added (`providers.md`), and a VERIFIED claim
or a READ line is held only to what this go did, not to the session it was
copied from. the step's line names the session it carried on as
`continued`.

the step starts fresh, with the whole prompt and the handoff, when its model
is not the one the session ran on, or when the words before what is new have
changed (an amended task, an edited role file, a brief that grew because a
step before it ran again), and when the session was kept more than a day
before (a stopped run carried on days later), which the console says. a
session kept past its cache's lifetime but within the day still carries on;
its line says `lapsed` (`journal.md`), since that call pays for the whole
session again. a different effort, such as
the level a send-back raises it to, carries on. a fanned-out step runs its
tasks side by side and cannot say `resume`; it is refused when the flow
loads. a provider that cannot carry a session on, such as `fake`, asks the
step fresh. an eval case records which sessions its steps went on from, and
its replay sends the same carried-on prompts. the api provider keeps a step's
messages for as long as the run runs and marks each prompt for the cache with the hour lifetime; a run
carried on in a new process starts its api steps fresh.

a step that waits a long while for its next call can lose its cache before
it gets there. `--keep-warm` sends a session that has waited its cache's
lifetime less five minutes (less one minute for a five-minute cache) one
cheap call: a copy of the session that is never kept, at the effort the
session was made at (a call at another level is not shown to read the
cache the session wrote, so it is never asked at one), with the step's
tools listed and a hook that refuses every one of them, so it touches nothing
in the place. at most three per session, only within the run's caps, and
charged like any other call, to the step it keeps warm: its tokens and cost
are on that step's next line, or on a line of its own with `outcome` `warm`
when the step is not asked again (`journal.md`), so the run's spend is the
sum of its lines. the lifetime is read from where the session's
cache writes went; a session whose lifetime is not known is never warmed,
and one already past its lifetime is left to the step's own next call. when
the run ends, a warm call still in flight is ended and charged before the
run is written down. it is off by default: whether a warm call costs less
than the cache it keeps has not been shown. a run that stopped to wait for
you has no process left to warm anything with.

## 8. say who decides first

a step that cannot go on without a decision asks with a `NEEDS:` line, and the
run parks for you. `lead` names a step that is asked first:

    lead: planner

it is a step or a role of the flow (a role means its first step), or `none`,
which is the same as leaving it out. a fanned-out step cannot lead, and a name
that is no step is refused when the flow loads. the lead decides with
`DECIDED: <option>` and a `why:` line under it, and the step that asked runs
again with the decision. an `ESCALATE:`, a decision with no `why:`, or a
second ask of the same question comes to you, and so does what the step
acting on a decision does to a spec line or a test the run started with: a
decision is judged by what that step changes, not by the files it names. pick the step that already reads the spec for the whole flow:
build-feature leads with its planner, and fix-with-test, whose first step
writes the test, has `lead: none`. how it reads in a run is in
[the journal](journal.md#when-a-step-asks-for-a-ruling).

## 9. say how hard a step thinks and how much it says

two keys on a step trim what its model spends:

    - role: planner
      effort: low
      verbosity: terse
      tools: [read, grep]

`effort` is how hard the step's model thinks: `low`, `medium`, `high`,
`xhigh` or `max`. it is over the tier's level and under `--effort-for`
(`providers.md`, "how hard the model thinks"). the api sends it as
`output_config.effort`, `claude` as `--effort`, and a command that is not
`claude` cannot act on it: its line says `"applies": false`.

`verbosity` is how much the step says back: `normal`, which is the same as
leaving it out, or `terse`. a terse step gets `fragments/terse.md` after its
rules and a token cap: 8000, or 16000 at `high` and above, where thinking
needs the room. that is a quarter of the api provider's own default cap, not
of whatever cap the step would have had. a lower cap already set stays: a
`max_tokens` in the provider block on the api, a
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` in the run's environment on `claude`.

the api sends the cap as `max_tokens`, so it holds the answer and the
thinking before it. `claude` gets it as `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, which
holds every model turn of the step, a tool call's input included, so a file
written through a tool could be cut off inside that call. a terse step is
therefore refused when the flow loads if it may write a file: `writes:
tests`, `product` or `spec`, a `tools:` list with `write` or `edit`, or no
`tools:` and no `writes: none` at all. a command that is not `claude` gets the
words and no cap, which its line says. an answer cut off at the cap fails the
step when the provider reports `stop_reason` `max_tokens`. keep `terse` for
steps whose answer is short by nature: a plan, a verdict, a list.

any other word in either key is refused when the flow loads.

## 10. say whether the run looks back

every failed attempt already has a why on its line in `steps.jsonl`, and
`retro:` adds one last step that reads them. every shipped flow, and the
template, says

    retro: true

so the retro is on by default in what ships; a flow opts out with
`retro: false`, and a flow that says nothing runs none. `retro:
conditional` runs it only after a run that had something to look back at:
it changed a file (one that was already modified before the run does not
count; outside git the run cannot tell and it counts), had a failed
attempt, a gate that could not do its job, a refused write or a fact's
check that broke or could not run, or asked a question (a ruling written, a step that asked or was decided for, a park).
any other run prints `retro not run: conditional, and the run changed no
file, had no failed attempt, no gate issue and no question` and spends
nothing on it.

once the handoff is written, every run that ends hands the retro role
(`roles/library/retro.md`) its record, with the retro skill
(`skills/retro/SKILL.md`) as the procedure: first the reasons each step
gave for its work (its BECAUSE items, by seq and step, each with where it
came from and what it led to), which the retro reads a fact's `why` off
first, a fact born from one that cites a file line taking that line as its
evidence; then the why line of each failed
attempt (a gate that failed, a send-back, a stop), each gate that could not
do its job (an `issue`, `docs/gates.md`) and each shell write a step went on
past after the hook refused it, by seq and step; each step's DID, ASSUMED,
TRIED and DOUBTS lines, and each defect it found beside the change (its
ADJACENT items, `docs/journal.md`, "what each step hands over") with whether
it was fixed and by which test, a defect left not fixed being the retro's
`defect` fact; the rulings written in the run; the files git says
it changed; the project's facts that are stale or hold for those files
(`docs/journal.md`, "what is known about a file"); how many new facts it may
write; `why.md` when the run stopped short; and `handoff.md`. a clean run is
handed `- none failed` and the rest, so the retro keeps the facts even when
nothing went wrong. it writes `runs/<run-id>/retro.md`: per failed attempt
what failed, why, and which gate, prompt or `flow.yaml` key to change, the
one change to make first, and one FACTS block. it is granted `read` and
nothing else, whatever the flow's steps are granted.

the FACTS block is the one part the runner acts on (`runner/upkeep.py`):
a `fact`, a `supersede`, a `re-anchor` and a `retire` are done once each
holds against the record (`docs/guardrails.md`, "the facts only the runner
writes"), a new fact written as `by runner from retro`; a `guard` and a
`doc` change are appended to `facts/PROPOSED.md` for a person and never
applied. the runner renders `facts/INDEX.md`, a line per live fact and the
stale ones apart. what it did with each item, each refusal with its reason,
goes at the end of `retro.md` under "what the runner did with the FACTS
block", at the end of `handoff.md` under "the retro's proposals", and on the
retro's line in `steps.jsonl` as `facts` (`written`, `counted`, `changed`,
`refused`, `proposed`, `owed`). a block that does not parse writes nothing
and says so in one line; an answer with no block changes no fact.

    facts_per_run: 3

caps the new facts one run writes (3 when unsaid); the same claim on the
same scope as a live fact is counted on it (`seen: proposed 2, ...`), once a
run. a `gate-issue` or `defect` fact counted again climbs: in two runs it is
`important`, in three a guard is proposed for it marked `recurring`, from
four on the handoff lists it as hardening owed every run until it is
retired.

    lane: off

keeps the flow's runs out of the project's facts altogether: no heal at the
start, no fact handed to a step, nothing the retro proposes acted on (its
`retro.md` ends `the flow's lane is off, so the FACTS block was not acted
on`), and the retro is told it may write 0. a step is still held to leaving
`facts/` as it found it. `lane: project`, the default, keeps them in the
place (`docs/journal.md`, "what is known about a file"). yaml reads a bare
`off` as false, and false is off too. with the lane off no fact's check runs
either.

    conformance: fail

a fact can carry a `check:`, one grep the runner runs itself after every
step that changes a file in the fact's scope (`docs/guardrails.md`, "a
fact's check"). by default, `conformance: warn`, a broken check is said on
the step's line and in the handoff and the run goes on; `fail` makes it a
gate that sends the step back, and a resumed leg is held to a break the
last leg left. a check that cannot run is never counted as one that held:
it is said, and under `fail` the gate passes with an `issue`.

the rest of what it writes is advice, never a gate. a retro that errors or
comes back empty is a `retro.md` line in `steps.jsonl` with `outcome:
failed` and the why; one that cannot even write that line only prints why.
either way the run's outcome, exit code and journal status stay what they
were. its line has its cost and seconds like any step's and `won: none`; it
is not in the budget plan (`budget` is null), it comes after the handoff, so
the handoff's spend and chain leave it out while the journal line and
`manifest.json` count it, and a resumed run's handoff counts it among the
passes it picked up.

a run that stops to wait (for a ruling, a person, the provider's limit, the
budget or an interrupt), or one at its call cap, holds its retro and prints
`retro not run:` and why. its failed attempts are not lost: the leg that
carries the run on hands them to its own retro, with its own. an attempt one
retro was handed is not handed to the next, and a stop that waited is not a
failed attempt. a run a tool fault stopped (`exception`: the provider refused
the call outright, no credentials say, or the runner itself raised) holds it
too, with `retro not run: the run stopped on exception`: a provider that
refused a step refuses the retro the same way. its crashed attempt is still a
failed one for a leg that carries the run on. the retro is held the way a
step would be refused: a place
where a step left an instruction file (`docs/guardrails.md`, "the files that
brief the model") gets `retro not run: CLAUDE.md changed in ...`, since the
retro's model would start there and read it. `retro:` is true, false or
`conditional`; anything else is refused when the flow loads, and so is a step
whose role is `retro` or that reads `retro.md`. a scored eval case of the
flow runs it the same way (`evals/README.md`).

## 11. run it three times before you trust it

    python run.py my-flow --force

the first run tells you the prompt is wrong. the second tells you the output
shape is wrong. the third is the first one worth reading.
