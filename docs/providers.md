# providers

a provider answers a prompt. that is the whole interface:

    ask(prompt, timeout) -> Reply(text, detail)
    check() -> (ok, detail)

## the three

- **cli** (default) - shells out to a command, `claude` unless you say
  otherwise. how this started and still what i run.
- **api** - plain http, no sdk. reads `API_KEY`, `API_URL` and `MODEL` from the
  environment. the model id is never written down in the source, because a
  version string in a file is a thing that rots quietly and then surprises you.
- **fake** - replays canned text. see below.

## choosing one

per flow:

    provider:
      provider: api
      max_tokens: 8192

or per step, which is the reason this exists at all - the planner is cheap and
the reviewer is not:

    steps:
      - role: planner
        prompt: planner.md
        provider:
          provider: cli
      - role: reviewer
        prompt: reviewer.md
        provider:
          provider: api

## where a setting comes from

step, then flow, then environment, then the default in `runner/settings.py`.
that order is the same for every setting, including which provider is used, so
a step naming a provider always wins over the flow naming one.

## checking

    python run.py provider

says whether each configured provider is usable right now, without spending
anything.
