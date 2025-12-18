# flows

prompts and a runner for the things i want to happen without me sitting there.

## the flows

- summarise-and-check - read a folder, summarise it, then check its own summary
  against the source and delete what it cannot back up
- weekly-digest - what changed this week, what needs me, what can wait
- ops-check - read today's logs and only tell me what is wrong
- release-notes - a git log in, notes a person would read out

## setup

    pip install -r requirements.txt

copy .env.example to .env and point it at your folders.

    pip install -r requirements-dev.txt
    pytest

## running one

    python run.py weekly-digest

## how a flow is put together

each flow is a folder under flows/. flow.yaml says what the steps are and how
long they get:

    name: weekly digest
    steps:
      - role: planner
        prompt: planner.md
      - role: worker
        prompt: worker.md
        fanout: true
      - role: reviewer
        prompt: reviewer.md
    timeout: 300
    workers: 3

each role has its own .md next to it. anything specific to the one flow goes
in instructions.md.

the rules every role gets are split across two places at the moment:
fragments/ for the plain ones, and skills/ for the two i moved over to try the
folder-with-frontmatter format. both get concatenated onto every role prompt,
which is the point, but having two loaders for the same job is silly and one of
them is going to win.

fanout on a step means the step before it produced a list, and each line gets
its own call instead of handing the whole list to one.

the reviewer can answer VERDICT: redo. the work is then done again and handed
back to the reviewer, twice at most.

## what a flow promises

flow.yaml can carry a promises block:

    promises:
      inputs: the .md files in the inbox modified in the last 7 days
      outputs: three lists - what changed, needs me, can wait
      invariants:
        - no file appears in two lists
        - needs me is at most 5 lines
        - every line names a file

inputs and outputs are for me in six months. the invariants get appended to
every role prompt in the flow, so the thing doing the work is told what has to
be true, and the reviewer is told the same thing in the same words.

## when a run dies

    python run.py weekly-digest --resume

picks up the most recent failed run for that flow, at the step that failed,
with the output of the step before it. the journal is what knows where it got
to.
