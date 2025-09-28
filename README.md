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

## running one

    python runner.py weekly-digest

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

each role has its own .md next to it. the rules every role gets are in
fragments/. anything specific to the one flow goes in instructions.md.

fanout on a step means the step before it produced a list, and each line gets
its own call instead of handing the whole list to one.

the reviewer can answer VERDICT: redo. the work is then done again and handed
back to the reviewer, twice at most.
