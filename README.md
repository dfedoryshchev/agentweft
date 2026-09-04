# agentweft

a runner for multi step prompt flows. a flow is a folder: a spec that says what
it promises, and one markdown file per role. the runner reads the spec, runs
the roles in order, writes down what happened, checks the output against the
promises, and stops if it costs too much.

the specs are the warp, the agents are the weft.

## why

a flow that calls a model four times can go wrong in four places and tell you
about none of them. what this is really for is the boring half: knowing what
ran, what it produced at each step, what it cost, whether it kept its own
promises, and being able to pick it up when it dies halfway.

it started as a pile of prompts i was pasting into a terminal twice a week.

## five minutes

    pip install -r requirements.txt
    python run.py list
    python run.py minimal --force --flows examples

the examples run on a fake provider, so that works with no key and no setup.
`docs/quickstart.md` goes further.

## what a flow looks like

    flows/weekly-digest/
      flow.yaml       the spec: steps, promises, limits
      planner.md      what this flow asks of the role
      worker.md
      merge.md
      reviewer.md
      instructions.md rules for this flow only

what a role IS lives once, in `roles/library/`, and is appended to whichever
flow uses it. a flow with nothing to add to a role does not need a file for it.

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
- **a step says which class of model, not which one.** `model: high` on the
  reviewer and `mid` on the planner. the ids live in the environment, because a
  version string in a file is right for about a quarter.
- **every run is written down.** one line per run, every step's output on disk,
  and a run that dies can be picked up where it fell over.
- **nothing costs money without a cap.** a flow declares its own ceiling and
  the run stops at it, mid flow, keeping what it has.

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
- `docs/orchestrate.md` - the workflow layer, and why it is in here

## where it came from

this is extracted and sanitized from a private system i have been running on my
own work since 2025. the shapes are the same; the specifics are not. the flows
here are generic versions of ones that do real jobs against folders and logs
that are none of your business.

it does not reimplement tools. it orchestrates agents that already have them -
a cli, or anything speaking mcp - and governs what they are allowed to do:
budgets, promises, gates, and a preflight that can refuse an edit inside a hot
blast radius. that is the deliberate scope, not a gap.

it is one person's tool that got useful. it is not a framework, it does not
want to be, and if you need something with a plugin system you want a different
project.
