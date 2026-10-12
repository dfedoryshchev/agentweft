# providers

a provider answers a prompt. that is the whole interface:

    ask(prompt, timeout) -> Reply(text, detail, usage, cost, session, model, retryable)
    check() -> (ok, detail)

## the three

- **cli** (default) - shells out to a command, `claude` unless you say
  otherwise. how this started and still what i run. the command is started in
  the run's place (`workdir`, see `flows.md`), so it reads and edits files
  there. `claude` is called as `claude -p --output-format json` (plus
  `--model`, see tiers) with the prompt on stdin, because Windows caps a
  command line at about 32k characters; it is never passed `--resume` or
  `--continue`, so what a call reports is that call. any other command is
  called as `<command> -p <prompt>` and its stdout is the answer, as before.
  output is read as UTF-8 either way.
- **api** - plain http, no sdk. reads `API_KEY`, `API_URL` and `MODEL` (or
  `MODEL_HIGH` and friends, see tiers) from the environment. the model id is
  never written down in the source, because a version string in a file is a
  thing that rots quietly and then surprises you.
- **fake** - replays canned text. see below.

## what an answer carries

besides the text:

- `usage` - the tokens the provider counted. `usage.raw` is its block exactly
  as sent; beside it are the OpenTelemetry GenAI totals (`as_otel()` gives the
  `gen_ai.usage.*` names). their `input_tokens` INCLUDES cache reads and cache
  writes, which anthropic's own `input_tokens` does not, so the two differ by
  the cache. `cache_read_input_tokens` and `cache_creation_input_tokens` are
  parts of that total, not additions to it. `usage.requests` is how many
  requests the block sums: 1 from the api provider, None from `claude`, whose
  block covers every request its session made.
- `cost` - USD, as the provider stated it. `claude` reports `total_cost_usd`;
  the api provider reports none. it is kept beside the money the price table
  gives (`guardrails.md`), never in place of it.
- `session` - `claude`'s `session_id`.
- `model` - the model that answered: the keys of `claude`'s `modelUsage`
  (comma-joined when more than one did), or the api response's `model`.
- `models` - when more than one model answered a `claude` call, the usage of
  each, from `modelUsage`, so each is priced at its own rates; None otherwise.
- `retryable` - whether going again can help, from the http status behind a
  failure (429, 5xx), a timeout, or a missing binary; None when unknown.
  the runner goes again only on True, asks once on False, and reads the
  failure's words only when it is None.

any of these is None when the provider did not say. that is not zero: **fake**,
a command other than `claude`, and an error that came back without a usage
block all report nothing, and `reply.counted` is False for them. a `claude`
error that did report usage keeps it, because the attempt was still paid for.

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
to **cli** when the command is `claude`, which gets the resolved id as
`--model <id>` (no id anywhere, no flag: the cli's own default answers). any
other command is handed as it is, because which flag it takes for a model is
not ours to guess; **fake** answers from a file. those two carry the tier and
do not act on it.

it is the same word the workflow layer's agents have always used in their
frontmatter (`docs/orchestrate.md`), and that is not a coincidence - it is
where the word came from.

## a model per role

a flow can give a tier to a role rather than to each step:

    tiers:
      reviewer: low

and a run can say which model each role uses without the flow being edited:

    python run.py code-review --force --model-for reviewer=low,worker=opus

the flag can be given more than once. a value is a tier (`high`, `mid`,
`low`, resolved as above) or a model id, handed to the provider as typed - the
flow file still never holds an id. a role the flow does not have, a role given
twice or a role with no model is refused before anything is asked, and the
refusal lists the roles there are. a role run at two steps gets the model at
both, and a fanned-out role at every task.

which one wins, highest first: `--model-for`, the step's own `model:`, the
flow's `tiers:`, then whatever the provider would have used anyway. a tier from
`--model-for` also wins over a `model` named inside a `provider:` block; a tier
from the step or the flow does not, as above. a resumed run keeps the models it
was started with and refuses a different `--model-for`. every step's line in
`steps.jsonl` says what was asked for, where, and whether the provider could
act on it (`docs/journal.md`).

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
