# quickstart

five minutes. the first three steps need no key and no folders of yours.

## 1. get it running

    pip install -r requirements.txt
    python run.py list

that prints the flows, their roles, and when they run. nothing has been called
yet and nothing has cost anything.

## 2. run one without a model

    python run.py minimal --force --flows examples

the examples use the `fake` provider, which replays canned text, and they read
their inputs out of `examples/_inbox` and `examples/_logs`, which are in the
repo. so this works on a fresh clone with nothing set up.

`two-step` and `watch` are the other two. run `two-step` if you want to watch
work get sent back for a redo.

## 3. look at what a flow promises

    python run.py show weekly-digest

what it takes, what it gives back, and the invariants it is held to every time.
those get handed to every role, so they are instructions as much as checks.

## 4. point it at a model

    cp .env.example .env

fill in either nothing (the default `cli` provider shells out to a command
already on your PATH) or `API_KEY`, `API_URL` and `MODEL` for the http one.

    python run.py provider

says whether each configured provider is usable, without spending anything.

## 5. run one for real

    mkdir inbox && echo "# a note" > inbox/note.md
    python run.py weekly-digest --force

`INBOX=./inbox` is already in `.env.example`, along with `LOGS` and `WATCH` for
the flows that read those.

## 6. when it dies halfway

    python run.py weekly-digest --resume

picks up the last failed run of that flow at the step it died on, so the steps
that already succeeded are not paid for twice.

to work on one prompt without running the flow around it:

    python run.py step weekly-digest planner

that reads stdin, writes nothing down, and prints what came back.

## 7. what it cost

    python run.py spend

the last runs, one line each. `python rollup.py` is the wider view, and takes
`--flow x` and `--failed`.

## next

- `docs/writing-a-flow.md` - adding your own
- `docs/gates.md` - checks that are programs, not prompts
- `docs/guardrails.md` - spend caps and promises
