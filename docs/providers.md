# providers

a provider answers a prompt. that is the whole interface:

    ask(prompt, timeout) -> Reply(text, detail)
    check() -> (ok, detail)

## the three

- **cli** (default) - shells out to a command, `claude` unless you say
  otherwise. how this started and still what i run.
- **api** - plain http, no sdk. reads `API_KEY`, `API_URL` and `MODEL` (or
  `MODEL_HIGH` and friends, see tiers) from the environment. the model id is
  never written down in the source, because a version string in a file is a
  thing that rots quietly and then surprises you.
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

## tiers

naming a provider per step answers "who", and most of the time the question is
"how good does this one have to be". that is a tier:

    steps:
      - role: planner
        prompt: planner.md
        model: mid
      - role: reviewer
        prompt: reviewer.md
        model: high

`high`, `mid`, `low`, and the checker refuses anything else - a version string
in a flow file is exactly what a tier exists to avoid. the ids stay in the
environment:

    MODEL_HIGH=...
    MODEL_MID=...
    MODEL=...          the one that answers when a tier has nothing of its own

so a tier resolves to `MODEL_<TIER>` if there is one, and to `MODEL` if there
is not, which means one configured model is still a working setup and every
tier reads it. a `model` named inside a `provider:` block wins over both,
because naming one has already answered the question the tier was asking.

the tier is a model choice, so it means something to the **api** provider and
nothing to the other two. **cli** is handed a command, and which flag that
command takes for a model is not ours to guess; **fake** answers from a file.
both carry the tier and neither acts on it.

it is the same word the workflow layer's agents have always used in their
frontmatter (`docs/orchestrate.md`), and that is not a coincidence - it is
where the word came from.

## where a setting comes from

step, then flow, then environment, then the default in `runner/settings.py`.
that order is the same for every setting, including which provider is used, so
a step naming a provider always wins over the flow naming one.

## checking

    python run.py provider

says whether each configured provider is usable right now, without spending
anything. a tier gets its own line, because a step asking for `high` with no
`MODEL_HIGH` and no `MODEL` behind it is a working provider block and a broken
step.
