# agentweft

a runner for multi step prompt flows. a flow is a folder: a spec that says what
it promises, and one markdown file per role. the runner reads the spec, runs
the roles in order, writes down what happened, checks the output against the
promises, and stops if it costs too much.

the specs are the warp, the agents are the weft.

## why

i had a pile of prompts i was pasting into a terminal twice a week. this is
what that turned into over about a year of running it on my own work.

## five minutes

    pip install -r requirements.txt
    python run.py list
    python run.py minimal --force --flows examples

the examples run on a fake provider, so that works with no key and no setup.
`docs/quickstart.md` goes further.

## what a flow looks like

    flows/weekly-digest/
      flow.yaml       the spec: steps, promises, limits
      planner.md      one file per role
      worker.md
      merge.md
      reviewer.md
      instructions.md rules for this flow only

    name: weekly digest
    steps:
      - role: planner
        prompt: planner.md
      - role: worker
        prompt: worker.md
        fanout: true
      - role: reviewer
        prompt: reviewer.md
        gates:
          - gate: length
            max_lines: 40
    promises:
      inputs: the .md files in the inbox modified in the last 7 days
      outputs: three lists - what changed, needs me, can wait
      invariants:
        - no file appears in two lists
        - every line names a file
    max_calls: 20

## the ideas that survived

- **a flow is a spec.** the invariants are handed to every role, so the thing
  doing the work and the thing checking it are told the same rule in the same
  words - and then checked afterwards, because being told is not being checked.
- **roles argue.** the reviewer did not write the output and its prompt says
  so. it can send the work back, twice at most, and then it has to look at what
  came back.
- **gates are programs, not prompts.** a regex either matched or it did not.
  the `command` gate runs anything with a cli, so a check does not have to be
  code in here.
- **every run is written down.** one line per run, every step's output on disk,
  and a run that dies can be picked up where it fell over.
- **nothing costs money without a cap.**

## docs

- `docs/quickstart.md` - five minutes
- `docs/flows.md` - how a flow is put together
- `docs/writing-a-flow.md` - adding one
- `docs/gates.md` - checks that are programs
- `docs/guardrails.md` - spend caps and promises
- `docs/providers.md` - cli, http, fake
- `docs/mcp.md` - reading the runs from an agent, and feeding a flow context
- `docs/journal.md` - the journal, the rollup, and --resume
- `docs/architecture.md` - what the code is doing

## where it came from

extracted and sanitized from a private system i have been running on my own
work since 2025. the flows here are generic versions of ones that do real jobs.
