# flows

a runner for multi step prompt flows. a flow is a folder: a spec that says what
it promises, and one markdown file per role. the runner reads the spec, runs
the roles in order, writes down what happened, and stops if it costs too much.

i built it to stop pasting the same prompts into a terminal twice a week. it
now runs six of them.

## what a flow looks like

    flows/weekly-digest/
      flow.yaml       the spec: steps, promises, limits
      planner.md      one file per role
      worker.md
      merge.md
      reviewer.md
      instructions.md rules for this flow only

## running one

    pip install -r requirements.txt
    cp .env.example .env        # then point INBOX at a folder of .md files
    python run.py weekly-digest --force   # --force ignores the schedule

## the ideas that survived

- **a flow is a spec.** flow.yaml says what goes in, what comes out, and what
  has to be true every time. the invariants get handed to every role, so the
  thing doing the work and the thing checking it are told the same rule in the
  same words.
- **roles argue.** the reviewer did not write the output and its prompt says
  so. it can send the work back, twice at most, and then it has to look at what
  came back.
- **every run is written down.** one line per run in the journal, every step's
  output on disk. a run that dies can be picked up where it fell over.
- **nothing costs money without a cap.**

## docs

- `docs/flows.md` - how a flow is put together
- `docs/writing-a-flow.md` - adding one
