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
      instructions.md    rules that apply to this flow only

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

`steps` runs in order. each step gets the previous step's output appended to
its prompt unless it says otherwise, which is the whole chaining mechanism.
there is no structured handoff and so far it has not needed one.

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
which is the normal case.

`tools` on a step is what it may touch: any of `read`, `grep`, `write`,
`edit`, `shell`, `browser`, and the checker refuses a word that is not one of
those. it is a BOUNDARY CHECK, not a sandbox, and `guardrails.md` is exact
about the difference - the grant is put into the step's prompt and the step's
answer is read back against it. a step that says nothing has declared no
boundary and nothing is checked; `tools: []` is a step saying it may touch
nothing, which is a boundary and does get checked.

`fanout: true` on a step means the step before it produced a list, one line
each, and every line gets its own call instead of the whole list going to one
worker. the results come back in whatever order they finish, so a fanout step
almost always wants a merge step after it.

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

`schedule` is checked before anything runs. `python run.py weekly-digest
--force` ignores it.

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
  steps, fanout included - and handed back to the reviewer. twice at most.

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
