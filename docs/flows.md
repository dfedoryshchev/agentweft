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
      - role: worker
        prompt: worker.md
        fanout: true
      - role: merge
        prompt: merge.md
      - role: reviewer
        prompt: reviewer.md
    schedule: sunday
    timeout: 420
    retries: 3
    workers: 4

`steps` runs in order. each step gets the previous step's output appended to
its prompt, which is the whole chaining mechanism. there is no structured
handoff and so far it has not needed one.

`fanout: true` on a step means the step before it produced a list, one line
each, and every line gets its own call instead of the whole list going to one
worker. the results come back in whatever order they finish, so a fanout step
almost always wants a merge step after it.

`schedule` is checked before anything runs. `python run.py weekly-digest
--force` ignores it.

## what each role is for

- **planner** reads the source and decides what the work is. it does not do
  the work. keeping it honest about that is most of the prompt.
- **worker** does the work from the plan.
- **merge** stitches fanout results back into one thing.
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
