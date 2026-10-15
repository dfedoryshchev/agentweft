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
  `--continue`, so what a call reports is that call. it is also handed
  `--settings` with the commit and pull request attribution off (below), and
  a step with `tools` gets its grant as flags (below). any other command is
  called as `<command> -p <prompt>` and its stdout is the answer, as before,
  grant or none. output is read as UTF-8 either way.

  the call is over when its answer is: for `claude`, once the json result has
  arrived (it then gets a few seconds to exit on its own), for any other
  command once it exits. a shell it moved to the background and left running
  would otherwise hold its output open and keep the step waiting to its
  timeout. so the command runs in a process group of its own (on Windows, a
  job object, which also holds a shell whose parent has exited), and whatever
  is still running when the call is over, or when it times out, is ended.
  how many that was is the reply's `killed`, and `background_killed` on the
  step's line (`journal.md`).
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
- `killed` - how many processes a cli call left running that were ended with
  it; None from a provider that starts none.
- `metered` - where the usage of a go `claude` never answered for came from;
  None for every go that answered. a call that timed out printed nothing, so
  its session's transcript is read back: the file under the cli's projects
  folder started in the call's window whose first message is the prompt (no
  session id was printed to find it by). its requests are summed, one per
  message, and `metered` is `"transcript"`. with no such file the go is
  `"estimate"` and `guess` is the prompt's length in tokens, at four
  characters a token. a call that exited with an error and printed no result
  is read back the same way, and left unestimated when there is no
  transcript, because it most likely never reached a model.

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

## a grant reaches the cli

a step's `tools` (`flows.md`) is handed to `claude` as the cli's own
permission flags, so the cli's permission layer holds the step to it. this
runner still sees no tool call; it passes config and records what it passed.

each grant word is the built-in tools that do what it says:

    read      Read, Glob
    grep      Grep
    write     Write
    edit      Edit, NotebookEdit
    shell     Bash, PowerShell
    browser   WebFetch, WebSearch

and a granted step is started with:

- `--tools <the tools>`, the fence: a tool it does not name is not there.
  `tools: []` is `--tools ""`, no tools at all.
- `--allowedTools <the same tools>`. under `dontAsk` anything that would
  prompt is denied, so a granted Bash or Edit has to be pre-approved to run at
  all. on its own this flag fences nothing; `--tools` does.
- `--permission-mode dontAsk`, pinned, because the mode a `-p` run starts in
  otherwise depends on the host.
- `--strict-mcp-config` and `--disallowedTools "mcp__*"`: `--tools` does not
  reach MCP tools, so the place's `.mcp.json` is not loaded and no MCP tool is
  left.
- `--disable-slash-commands`, no skills or commands.
- for a grant that only looks (no `write`, `edit` or `shell`), `--restricted`:
  the command and code running tools and WebFetch are gone unless `--tools`
  names them, the file tools stay inside the working directories, and no user,
  project or local settings file is read.
- for a grant that acts, `--setting-sources user`: the user's own settings
  load and the place's `.claude/settings.json` and `settings.local.json`, with
  their hooks, `env` and key helper, do not.

`--settings '{"disableAllHooks":true}'` is not passed on purpose: it would
turn off a hook the run hands over itself, and the place's hooks are already
kept out by which settings sources load. `--bare` is not passed either: it
authenticates only by API key.

the floor is `claude` 2.1.295, the first release in which `--tools` and
`--restricted` also apply to the built-in tools that register after launch;
below it the fence fails open. so a step with a grant asks `claude --version`
once and is refused before it starts, with the version in the reason, when the
cli is older or says something that is not a version. a step without a grant
is not held to it.

the step's line in `steps.jsonl` keeps the grant, every flag it became (the
command line minus the command; the prompt is on stdin) and the version
(`journal.md`).

every flag and setting above is checked against `claude --help` and the
cli's own reference for 2.1.296. a command other than `claude` is handed
none of this, because which flags it takes is not ours to guess: its grant is
recorded as not enforced, and it gets the prompt and the after-the-fact check
only (`guardrails.md`).

### the attribution trailer

`claude` adds a `Co-Authored-By` trailer to the commits it makes and a line to
the pull requests it opens unless told otherwise. every `claude` call here is
handed `--settings '{"attribution":{"commit":"","pr":"","sessionUrl":false}}'`,
which turns all three off. a run that wants them sets it in the provider
block:

    provider:
      provider: cli
      co_author: true

and `--settings` is then not passed at all, so the cli's own default answers.

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

for `claude` the line says the version, whether it is logged in and how
(`claude auth status`, by its exit code and its `authMethod`; the account is
never printed), and the model a step would ask for, or the cli's default. a
version below the floor fails the check, because every shipped reviewer
carries a grant and would be refused. neither question makes a model call.
