# how a flow is put together

(adding one: `writing-a-flow.md`. the journal and --resume: `journal.md`.)

a flow is a folder under `flows/`. nothing outside that folder knows anything
about it, which is the point: adding a flow should not mean editing python.

## the files

    flows/weekly-digest/
      flow.yaml          what the steps are and how long they get
      planner.md         what this flow asks of the role, and nothing else
      worker.md
      merge.md
      reviewer.md
      instructions.md    rules that apply to this flow only. may be left out

## the task a run is given

a flow that works on whatever it is pointed at says where that goes by writing
`{TASK}` in its own words:

    # worker

    here is a bug. do not fix it.

    {TASK}

then one flow serves every bug:

    python run.py fix-with-test --task "add(1, 2) returns -1"
    python run.py fix-with-test --task-file bug.md

`--task-file` is read as UTF-8, a byte order mark dropped. the text goes in
exactly where `{TASK}` is and nowhere else: in a step's own file it reaches
that step, in `instructions.md` it reaches every step. a fanned-out flow that
names it in `planner.md` hands it to the planner, and the workers get the
plan. `{INBOX}` and friends are put in first, so a task that quotes one keeps
it as written.

the run is refused, before anything is called or written, when:

- the flow has no `{TASK}` and a task was given: it would go nowhere
- the flow has one and no task was given: a worker told "here is a bug" with
  no bug answers anyway
- both switches are given, or the task is empty, or the file is missing or
  not UTF-8

the task is kept as `runs/<id>/task.md`, every `steps.jsonl` line names it
(`"task_file": "task.md"`, null for a run without one), and a parked run's
`handoff.md` carries its first line. `--resume` carries on with it, so the
command in the handoff needs no `--task`; a resume told a different one is
refused. `python run.py show <flow>` says which files take it.

the mcp `run_flow` tool takes an optional `task`, an eval case gives one as
`task:` in case.yaml or a `task.md` beside it, and `cron.py` skips a flow that
takes a task, saying so, since it has none to give.

## the spec as the run found it

a reviewer called after a step edited the spec, and handed only the spec as
it is now, reviews the change against the edit it was there to catch. so a
step's own words can name two more values, filled each time the step is
called:

- `{SPEC_AT_START}`: every spec file (`TASK.md`, `SPEC*.md`, `docs/spec*`
  from the top of the place) as the run found it, under its path, read from
  the start commit, or from the start snapshot for a file already loose, and
  never from the work tree
- `{SPEC_DIFF}`: what has changed in them since, as a unified diff, or
  `(no change: ...)`

a flow whose prompts name either takes the start snapshot even without
`spec_files:`. both reviewers that ship with it, `build-feature` and
`code-review`, read them.

a step whose own words name one of them and ask for a verdict is held to it:
an `ok` while the spec has moved is a redo, unless each line that moved,
added, removed or rewritten, is quoted by an entry in `decisions.md` (the
same quote that lets a spec line change, `guardrails.md` "the spec files").
in a flow with `spec_files: additions` an added line is allowed, so only a
removed or rewritten one counts there; under `read-only`, or with no
`spec_files:`, every moved line does. the reviewer's answer goes back with the lines named, `TASK.md:4` and so on,
and the step it sends back to puts the spec back or asks for a ruling. a
reviewer's own redo stays its own.

## flow.yaml

    name: weekly digest
    steps:
      - role: planner
        prompt: planner.md
        model: mid
      - role: worker
        prompt: worker.md
        fanout: true
      - role: merge
        prompt: merge.md
      - role: reviewer
        prompt: reviewer.md
        model: high
        tools: [read, grep]
    schedule: sunday
    timeout: 420
    retries: 3
    workers: 4

a key nothing reads is refused when the flow loads, with the key it was
probably meant to be: at the top, on a step, inside `promises`, `context`,
`preflight`, and on a gate, where an unknown gate name is refused with the list
of the ones there are. a misspelt gate used to load and fail only after its
step had run and been paid for.

`steps` runs in order. each step gets the previous step's output appended to
its prompt unless it says otherwise, which is the whole chaining mechanism.
on top of it goes the previous step's HANDOFF block, parsed: the constraints
in force, what it assumed and doubts, what it verified and how, what it read
(see "what each step hands over" in `journal.md`).

`role` is what a step IS and `prompt` is only where its words are kept, so one
role can be two steps with a file each. that is how a flow runs a reviewer
twice from two fixed positions - one told to cut, one told to say what is
missing - and it is worth doing because one reviewer asked for a balanced view
gives you a balanced view. both steps get the role's contract out of
`roles/library/`; what differs is the flow's own file. a pair like that wants
a step after it that ends the argument, which is `reports` below.
`examples/personas` is the whole shape in four steps.

`model` on a step is a TIER - `high`, `mid` or `low` - and never a model id.
the planner is cheap and the reviewer is not, and that is a fact about the
steps rather than about whichever model is current this quarter. which id a
tier resolves to lives in the environment; `providers.md` has the mapping. a
step that says nothing gets whatever the flow's provider is configured with,
which is the normal case. `tiers:` at the top of the flow gives a tier to a
role at every step it runs, under a step's own `model`, and `--model-for` on
the run is over both (`providers.md`, "a model per role").

`effort` on a step is how hard its model thinks: `low`, `medium`, `high`,
`xhigh` or `max`. `efforts:` at the top of the flow gives a level to a role,
under a step's own `effort`, and `--effort-for` on the run is over both. a
step sent back goes again one level higher (`providers.md`, "how hard the
model thinks").

`sacrifice:` at the top of the flow is what a run gives up, in order, when
its budget plan does not fit the cap: steps or roles, one per line, never one
that guards the tests (`guardrails.md`, "what a flow gives up when it does
not fit").

`tools` on a step is what it may touch: any of `read`, `grep`, `write`,
`edit`, `shell`, `browser`, and the checker refuses a word that is not one of
those. it is not a sandbox of agentweft's own, and `guardrails.md` is exact
about the difference - the grant is put into the step's prompt, handed to
`claude` as the cli's own permission flags (`providers.md`), and the step's
answer is read back against it. a step that says nothing has declared no
boundary, nothing is passed and nothing is checked; `tools: []` is a step
saying it may touch nothing, which is a boundary: `claude` gets no tools at
all, and the answer is checked. every shipped reviewer is granted
`[read, grep, shell]`, so it can run the command that reproduces a finding.

`investigate:` puts one step in front of the flow's own, `investigator.md`,
which finds the cause of the task and everything it reaches before anything is
written. `off` is the default and the flow exactly as it was. `cause` asks for
`CAUSE:` (the line and why), `SITES:` (every place sharing the cause, one
`file:function` a line, no code), `FEEDS:` (the commands and callers the
change feeds), `RELATED:` (other defects seen on the way), `ROOTED: yes|no`,
`RULED OUT:` and `REPRO:` (the command actually run). `plan` asks for all of
that plus `TESTS:` per affected command and `DECISIONS:` for the person. the
step is granted `[read, grep, shell]`, must produce `CAUSE:`, and stops the
run there when no site has a file and a function or there is no `ROOTED:`
line. `ROOTED: no, <what is unknown>` parks the run for a person instead of
fixing a guess; editing that step's output and resuming is how to hand it the
missing piece. every step after it is handed the labelled lines and nothing
else, in place of the raw answer. `RELATED:` and `DECISIONS:` never reach the
fix: they are added to the run's saved output. it takes the task, so a flow
with `investigate:` on takes one. a flow file that writes `{SCOPE}` gets
what a patch may touch there: what the test reaches when nothing was
investigated, the named sites when something was (`fix-with-test/patcher.md`).

`auto` is `cause` held back until the flow's first own step shows it needs
one: its red test failing a second time, or its handoff naming more than one
cause under `DID:`. then the step runs once, the first step runs again with
the labelled lines, and the run's `decisions.md` says what switched it on. a
run that never shows either never pays for the step, and a red test that
fails again after it stops the run as it would without it.

`verify:` is `judge` or `off`. `judge` runs the flow's steps of role `verify` as
written, `off` takes them out when the flow loads, and a flow that does not
say runs them as written. it is for a flow whose promises are all gates on the
steps before, where the judge can only fail what the programs passed:
`fix-with-test` ships `verify: "off"` (`gates.md` has the why, and
`writing-a-flow.md` how to write promises a gate can show).

`fanout: true` on a step means the step before it produced a list, one line
each, and every line gets its own call instead of the whole list going to one
worker. the calls run side by side and the results are joined in the order
of the list, so a fanout step almost always wants a merge step after it.
a line is a task when it has a `|` in it. a list with none stops the run at
the step that wrote it, `failed at <that step>` with `no tasks:` at the start
of the why, and `--resume` asks that step again.

`reports: [worker, reviewer]` on a step names the steps whose output it is
handed, instead of only the one before it. it is the other kind of many:
`fanout` is one role in copies and `merge` stitches those copies back together,
while a step with `reports` is given several different roles' work and has to
decide between them. each report arrives under the name of the step that wrote
it, because a judge that cannot tell whose report is whose can only average
them. the conflict table out of `orchestrate/agents/architect.md` goes with
them, and `roles/library/judge.md` is what the role itself is told.

a name in that list is a ROLE or a STEP. a role stands for every step that
declared it, a step stands for itself and is its prompt file without the
`.md`, and in a flow whose files are named after their roles the two are the
same word. so `reports: [reviewer]` over one reviewer is the one report it has
always been, and over a pair of them it is both, under a name each - which is
the only form a judge can do anything with. `reports: [reviewer-minimalist]`
names one of the pair. the same step named twice arrives once. a name that is
neither a role nor a step earlier in the same flow is refused by the checker.

`writes: tests | product | none` on a step is what it writes, and the runner
holds the order: a product step does not start before the run holds a red
test, a tests step that changes product code fails (`docs/gates.md`, "no
product code before a red test").

`writes_tests: true` on a step means it writes the tests around the change
once the change is green, and it is sent
`fragments/tests.md` after its own words: every behaviour, input class, output
shape, error path, caller and option pair the change reaches, each case once,
expected values from the spec and never from running the code, and a
`NEEDS:` line for a case the spec does not decide. the levels go in as values,
one line each: unit always; integration from `tests_integration` at the top of
the flow - `true`, `false`, or `auto` (the default), which is on where the
project has an entry point (`[project.scripts]` in `pyproject.toml`, a
`__main__.py` at the top or in a package one level down, or a `main.py`); e2e
from `tests_e2e`, off unless the flow turns it on. a level that is off is
named in the prompt as one not to write. `fix-with-test` marks its patcher,
`build-feature` its worker. the step that writes the first tests is not
marked: the fix-with-test worker writes the minimum that fails for the reason
the report gives, and the build-feature tester one test per planned behaviour
and nothing beyond them. the fix-with-test worker still looks for every place
the symptom can come from before it writes that test, following the input
through the code and probing it (a probe never sets what a test expects), and
names each cause it finds; the patcher fixes and tests each named cause or
says in a doubt why not. those first tests are what the request is checked against the
spec on, so a run that stops on a `CONFLICT:` stops before anything is spent
on cases for a request that may be wrong. the cases written after green are
replayed by the `red-first` gate, which reports each one as red without the
change or as a pin (`docs/gates.md`).

`schedule` is checked before anything runs. `python run.py weekly-digest
--force` ignores it.

`workdir` is the directory the run works in, and `--workdir <dir>` on the
command line beats it. a run that names neither works where `run.py` was
started, and a relative path is resolved against that same directory. it is
made absolute once, before the first step is asked anything, and a place that
is not a directory stops the run right there. the run holds the result as
`Run.workdir` and writes it to `runs/<run-id>/workdir`, so `--resume` carries
on in the place the run started in, whatever the flow file says by then; a
resume told `--workdir` somewhere else is refused. the `command` gate runs its
command there, so a suite in that directory is a gate on its exit code, and
the `cli` provider starts its command there, so a model that edits files edits
the place and not whatever directory `run.py` happened to be started from.
that last part has a guard of its own, in `guardrails.md`.
`runs/` is not part of the place: it is always the one beside `run.py` in the
agentweft checkout, whichever directory the run was started from or works in,
so a run pointed at another repo leaves no run records in that repo's tree.

`worktree: true`, or `--worktree` on the command line, makes the run work in a
git worktree of its own instead of the place. before the first step the run
adds a detached `git worktree` of HEAD (or of the commit named:
`--worktree <commit>`, `worktree: <commit>`) under
`runs/worktrees/<run-id>`, with the repo's hooks off, and the place inside it
becomes `Run.workdir`. every step, every gate, the start snapshot and the
changed-file record then read that worktree, so nothing the run does reaches
the tree it was started from, byte for byte. the loose changes in that tree
are not carried over: the run starts from a commit. the worktree's path and
the commit it was made from go into the manifest, and the handoff names both
with the commands that bring the change back (a branch there, merged where
you work, or a patch). a resume carries on in the same worktree; `--worktree`
on a resume of a run that did not start in one is refused. the worktree is
left for you to read: `python run.py worktree` lists them, and
`python run.py worktree remove <run-id>` removes one, refusing while it holds
a file not committed or a commit no branch holds (`--force` removes it
anyway). without the key or the flag a run works in the place, as above.

## what each role is for

- **planner** reads the source and decides what the work is. it does not do
  the work. keeping it honest about that is most of the prompt.
- **worker** does the work from the plan.
- **merge** stitches fanout results back into one thing.
- **judge** is handed several reports that disagree and answers with one
  verdict. it is not merge with more inputs: merge is told to add nothing that
  was not already in one of the parts, and deciding between two reports is
  exactly something neither of them said.
- **reviewer** did not write the output and says so in its prompt. it can
  answer `VERDICT: redo`, and then the work is done again - through the same
  steps, fanout included - and handed back to the reviewer. twice at most: a
  redo after that parks the run at the reviewer for a person, the same park a
  `pause` gives (see `journal.md`), with the reason in its `handoff.md`.
  the verdict is the first line of the answer, read whatever its case and
  without a closing full stop. a step whose prompt carries the verdict block
  (a reviewer, a judge) and answers anything but ok or redo, or has no verdict
  line, stops the run there with what it said quoted: only redo is acted on,
  so anything else would walk on as if it were ok. a step that was never
  told to give a verdict goes on without one.

## the rules every role gets

`fragments/` is concatenated onto every role prompt in every flow. that is
where "markdown only", "no preamble" and "never invent a number" live. if a
rule is true for every flow it belongs there, not copied into four files.

## the words a role gets in every flow

`roles/library/` is the same idea one level down. fragments are what every
role is told; the library is what one role is told wherever it turns up - a
reviewer answers with a verdict line, a merge adds nothing that was not in the
parts, a planner does not do the work, a verify does not improve what it was
handed.

the flow's own file is read first and the library's words are appended after
it, which is where every flow had already been putting them by hand. the
verdict block was pasted into five reviewers and missing from the sixth, which
is the argument for the whole thing in one sentence.

a role the library has words for does not need a file in the flow at all: with
nothing to add, the library IS the prompt. that is why `flows/_template` ships
one role file instead of four. a role it says nothing about - `worker` is the
honest example, since almost all of what a worker is told is about the flow it
is in - is the flow's own text and nothing else.
