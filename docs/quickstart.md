# quickstart

five minutes, no key needed for the first three.

## 1. get it running

    pip install -r requirements.txt
    python run.py list

that prints the flows, their roles, and when they run. nothing has been called
yet and nothing has cost anything.

## 2. run one without a model

    python run.py minimal --force --flows examples

the examples use the `fake` provider, which replays canned text. this proves
the wiring works before you point it at anything real.

## 3. look at what happened

    python run.py show weekly-digest

what it takes, what it gives back, and what it promises every time.

## 4. point it at a model

    cp .env.example .env

fill in either nothing (the default `cli` provider shells out to a command
already on your PATH) or `API_KEY`, `API_URL` and `MODEL` for the http one.

    python run.py provider

says whether each configured provider is usable, without spending anything.

## 5. run one for real

    mkdir inbox && echo "# a note" > inbox/note.md
    INBOX=inbox python run.py weekly-digest --force

then `python rollup.py` for what the week cost.

## next

- `docs/writing-a-flow.md` - adding your own
- `docs/gates.md` - checks that are programs, not prompts
- `docs/guardrails.md` - spend caps and promises
