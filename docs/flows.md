# how a flow is put together

a flow is a folder under `flows/`. nothing outside that folder knows anything
about it, which is the point: adding a flow should not mean editing python.

## the files

    flows/weekly-digest/
      flow.yaml          what the steps are and how long they get
      planner.md         one file per role
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

`schedule` is checked before anything runs. `python runner.py weekly-digest
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
