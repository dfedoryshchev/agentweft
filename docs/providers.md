# providers

a provider answers a prompt. that is the whole interface:

    ask(prompt, timeout) -> Reply(text, detail, usage, cost, session, model, retryable)
    check() -> (ok, detail)

a step picks who answers it by a provider block or by a connector's name
("connectors" below): `claude-sub` on the subscription login, `claude-api`
on an api key, `stub` for tests, or one a project declares. two of them can
run side by side in one flow, and every step's line says which one paid.

## the three

- **cli** (default) - shells out to a command, `claude` unless you say
  otherwise. how this started and still what i run. the command is started in
  the run's place (`workdir`, see `flows.md`), so it reads and edits files
  there. `claude` is called as `claude -p --output-format json` (plus
  `--model` and `--effort`, see tiers) with the prompt on stdin, because Windows caps a
  command line at about 32k characters. it is never passed `--continue`, and
  `--resume` only for a step with `continue: resume` (`writing-a-flow.md`):
  `--resume <id> --fork-session --session-id <new id>`, a copy of the step's
  last session under an id chosen before the call. a fresh step is passed no
  session flags at all. what a carried-on call reports was read off
  `claude` 2.1.301, one fresh call and one `--resume --fork-session` of it:
  `usage` is that call's own, while `modelUsage` and `total_cost_usd` run on
  from the session it was copied from. so the reply's `usage` is kept as it
  came, and its `models` and `cost` are the reported ones less the
  session's earlier figures; a figure below the earlier one is kept as it
  came, and a cost with no earlier figure to take out is None. the copy's
  transcript starts with the earlier session's rows, message ids unchanged,
  so the checks that read a transcript (a VERIFIED claim's command, what a
  pass read, shell traps, a go that never answered) leave those rows out.
  it is also handed
  `--settings` with the cli's model switch off and the commit and pull
  request attribution off (both below), and a step with `tools` gets its
  grant as flags (below). any other command is
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
  thing that rots quietly and then surprises you. a step with `continue:
  resume` is sent its earlier messages and answers with the new prompt, the
  new prompt marked `cache_control` with the hour lifetime (`"ttl": "1h"`);
  the messages live as long as the process.
- **fake** - replays canned text. see below.

## what an answer carries

a text the model never wrote is not an answer. `claude -p` prints a result
even when nothing reached the model: a `UserPromptSubmit` hook in the
operator's own cli settings that refused the prompt, a wrapper in front of
the binary, the cli's own notice. such a result exits 0 with `is_error:
false`, and its text may echo the prompt, the role's answer template
included, which a gate would read as claims. so a result that printed
`num_turns: 0` and counted no output token is the cli answering without the
model (`cli_provider.no_model_ran`, read before a carried-on call's turn
count is dropped): no text, not retried, the first line of what it printed in
the reason, and the step is not sent back. a cli that prints no `num_turns`
is read as before. the run stops on it as a tool fault.

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
- `session` - `claude`'s `session_id`, or for a step that carries its
  session on, the id its call wrote.
- `kept` - for a call made to be carried on, what its session used as a
  whole (`usage`, `models`, `cost`, as reported), which the next call's is
  taken from; None otherwise.
- `model` - the model that answered: the keys of `claude`'s `modelUsage`
  (comma-joined when more than one did), or the api response's `model`.
- `models` - when more than one model answered a `claude` call, the usage of
  each, from `modelUsage`, so each is priced at its own rates; None otherwise.
- `retryable` - whether going again can help, from the http status behind a
  failure (429, 5xx), a timeout, or a missing binary; None when unknown.
  the runner goes again only on True, asks once on False, and reads the
  failure's words only when it is None: words it does not know read as worth
  going again, and a message the provider's safeguards flagged
  (`safeguards flagged`) reads as not, since the same prompt is flagged again
  and each go is charged for all of it.
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

## connectors

a connector is a provider block with a name, declared once and picked by
that name on a step, beside the step's model:

    steps:
      - role: planner
        prompt: planner.md
        provider: claude-sub
        model: mid
      - role: worker
        prompt: worker.md
        provider: claude-api

three are built in and need no declaring:

    claude-sub   provider: cli, auth: subscription
    claude-api   provider: cli, auth: api-key (reads the file AGENTWEFT_KEY_FILE names)
    stub         provider: fake

more are declared under `connectors:` in the flow or in `project.yml`, each a
provider block (every key the provider takes) plus `auth` and `key_file`:

    connectors:
      cheap:
        provider: cli
        model: m-cheap
      mine:
        provider: cli
        auth: api-key
        key_file: ~/.config/agentweft/other-key

a declaration merges over the built-in of its name; the flow's declaration
merges over `project.yml`'s. a name that is a provider's own (`cli`, `api`,
`fake`) is refused, and so is a step naming a connector there is not, before
anything is asked, with the names there are. an inline block (`provider:
{provider: cli, ...}`) works as it always did, and the flow's `provider:` may
be a connector's name too.

where a credential comes from and where it goes is yours to say, never the
project's. `project.yml` is the repo's file: a clone ships one, and a step
can write it for the next run. so a connector `project.yml` declares may set
only a listed key: a provider (`cli` or `api`; the stub is a flow's, never
the project's), a model or tier, an effort, `auth: subscription` or
`inherit`, and the provider's tuning (`max_turns` no looser than yours,
`max_tokens`; `orchestrate.md`). on a built-in's name (`claude-sub`,
`claude-api`, `stub`) it may set only `model`, `tier`, `effort` and
`max_turns`, where the built-in takes them: what a built-in runs on and which
login it uses stay as shipped. any other key is refused at load, the file and
the key named; `auth: api-key`,
`key_file`, `command`, `url` (the **api** provider's endpoint) and `env`
(which of your variables reach the model's process) are said in the flow you
run or in your own environment.

the key file of a connector with `auth: api-key` is its own `key_file`, said
in the flow, else the file `AGENTWEFT_KEY_FILE` names: set it in your shell,
or in the `.env` that `agentweft init` writes where you start agentweft. a
`.env` inside the place is the project's file, so a key file named there
refuses the run before any process starts, with that `.env` named
(`quickstart.md`).

a credential goes to the `claude` cli and to the **api** provider's own
request, and to no other command. so a built-in connector's `command` is
never declared again (`claude-api: {command: python}` is refused at load, with
that reason), a declared connector with `auth: api-key` whose `command` is not
`claude` is refused at load, and a connector with `subscription` or `api-key`
whose `claude` lies inside the place (`tools/claude`, `./claude.cmd`) or in
agentweft's runs folder (a run's `tmp` is the steps' scratch, and it outlives
the run) is refused before its call: a step could have written it. a bare
`claude` is judged where `PATH` finds it, once per run, and the file found is
the step line's `command_path` (`journal.md`), so a `PATH` that moved shows.
`claude` is told by its file name (`claude`, `claude.cmd`, `/usr/bin/claude`),
the same test the provider uses for its flags, so a wrapper named `claude`
outside both folders is handed the credential like the cli; and the lookup
is python's `shutil.which` over `PATH`, which on Windows can differ from the
system's own search for a bare name; a `command` written as a full path
outside both folders is the one exact way to say which file starts.

every `claude` step loads your own settings only, never the place's (below,
"a grant reaches the cli"). as a belt beside that, a step on `subscription`
or `api-key` with no grant is started with `--settings` naming
`ANTHROPIC_BASE_URL` (the command line ranks above every settings file but
your organisation's managed ones): the value your own settings file's `env`
block gives, else the run's environment's, else the api's own host. a step
with a grant loads only your settings file, or none, and is left as it is.
under `inherit` nothing is pinned: a key exported in your shell reaches the
step as it always did, and your own settings decide where it goes.

`auth` decides the credential the step's process is handed, and no other:

- `subscription`: `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are taken
  out, and with them the switches the cli would log in with ahead of its
  login (`CLAUDE_CODE_USE_BEDROCK`, `_MANTLE`, `_ANTHROPIC_AWS`, `_VERTEX`,
  `_ANTHROPIC_GOOGLE_CLOUD`, `_FOUNDRY`, the gateway mode's `_GATEWAY` with
  its `CLAUDE_CODE_GATEWAY_TOKEN` and `_FILE_DESCRIPTOR`, `ANTHROPIC_PROFILE`
  and the federation pair), every cloud route's names (below, "what the
  command's process holds") and the cloud keys (`AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_BEARER_TOKEN_BEDROCK`,
  `AZURE_CLIENT_SECRET`, `AZURE_CLIENT_CERTIFICATE_PASSWORD`), so `claude`
  falls to its own subscription login (`CLAUDE_CODE_OAUTH_TOKEN` stays: it
  is that login). a step that acts loads your own settings file, whose `env`
  block the cli writes over the environment it was started with, so every
  one of those switches is also set to `""` in the `--settings` the step is
  started with, which sits above your settings file: the cli reads an empty
  switch as off, so a route your file switches on is off for the step.
- `api-key`: the same names and both login tokens
  (`CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`) are taken
  out, and `ANTHROPIC_API_KEY` is the key read from the key file when the call
  starts, never before, never on the command line, never written into the
  run's files. the call also gets `CLAUDE_CODE_PROMPT_CACHE_TTL=1h`: on an
  api key the cli's prompt cache lives 5 minutes unless asked for the hour,
  and a step waiting on a gate or a sibling often waits longer (the
  subscription gets the hour on its own). the name is checked against the
  cli's env-vars reference (it needs 2.1.242 or later; a
  `FORCE_PROMPT_CACHING_5M` named in the block's `env:` overrides it).
- `inherit` (the default, and every inline block that says no `auth`): the
  credentials the run holds, under "what the command's process holds"; a
  named connector on `inherit` also gets the subprocess scrub (below), an
  inline block does not.

which `claude` steps are started with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`:

- a step on a named connector (a built-in or one declared under
  `connectors:`), whatever its `auth`, `inherit` included; when the run's own
  environment already sets the name, its value is kept.
- a step whose `auth` is `api-key`, named or written inline, always gets `1`.
- a provider block written inline with `subscription` or `inherit`, and the
  flow's default provider when it names no connector, get nothing: they run
  as they did before connectors.

the cli then takes credentials out of the environment of the shell commands,
hooks and stdio MCP servers it starts, so a key the step was handed, or one
exported in your shell, does not reach a command the model runs; the cli
keeps it for its own calls. the cli knows a credential by its name or the
shape of its value, takes `CLAUDE_CONFIG_DIR` out too, and leaves
`GITHUB_TOKEN`, `GH_TOKEN`, the proxy names and `GIT_CONFIG_*` in place (its
env-vars reference, "What the subprocess environment scrub removes"). so
`claude-sub` and an inline block with the same settings do not give the
model's shell the same environment: under the connector a test that reads a
`DATABASE_URL` with a password, an `NPM_TOKEN`, or a nested `claude` that
needs `CLAUDE_CONFIG_DIR` loses it. the inline block is left without the
scrub on purpose: it is how a step whose tests need those variables keeps
them, and an inline block that carries a key still gets the scrub.

the key file is a full path (or starts with `~`) outside the place, so that no
run commits it, a step quotes it from the tree or a gate's command finds it
there: a key file inside the place is refused. outside is not unreadable: a
step's read tools are not fenced to the place, which is why the key is also
redacted wherever it shows up (below). a step
whose key file is missing or empty is refused before its call, with the
path in the reason, and the run stops there; nothing falls back to another
login. the **api** provider takes `auth: api-key` the same way, reading the
file instead of `API_KEY`; it has no subscription login. **fake** has no
login, so its auth is `inherit`.

two connectors in one run never see each other's credential: the key is read
from its file into the one call's environment and is never put in the
runner's own, and a `subscription` step strips any key the run was started
with.

every step's line in `steps.jsonl` says its `connector` and `auth`, and a
step on a `claude` connector the cli's own `authMethod`, read once per
connector a run (`journal.md`); the run's spend line and `python run.py
spend` split the calls the same way, so the record says which credential
paid for each step.

the `authMethod` is also checked against the connector's `auth` before the
step's first call, and a step whose cli would log in another way is refused,
with both named:

- `subscription` runs only on `claude.ai` (the `/login` subscription), or on
  `oauth_token` while the step's environment holds `CLAUDE_CODE_OAUTH_TOKEN`
  (a `claude setup-token` subscription token). anything else is refused:
  `api_key` (a key in an `env` block of the operator's settings, or one saved
  by an earlier Console login), `api_key_helper` (an `apiKeyHelper`),
  `oauth_token` with no such token (a named or federation profile), or
  `third_party` (a cloud provider switch in the settings). the cli ranks
  each of those above its login, and none is an environment name the strip
  can reach.
- `api-key` runs only on `api_key`; `claude.ai`, `oauth_token` or
  `api_key_helper` there means the key never reached the cli.
- a status that could not be read (not logged in, not JSON, no
  `authMethod`) is refused too: nothing says which credential would pay.
- `inherit` is never refused, and nothing is checked for a command other
  than `claude`, which is handed no credential, or for the **api** provider,
  which sends the key file's key itself.

the values are the ones the cli prints today (2.1.323: `claude.ai`,
`api_key`, `api_key_helper`, `oauth_token`, `third_party`, `none`); a value
a later cli adds is refused until this list names it.

### on an api key

three more things hold whichever connector a step runs on, and matter most
on an api key:

- a gate's command, the run of the start tests and the sign-off's git start
  without any `ANTHROPIC_` name, either login token or `API_KEY`
  (`gates.md`), so a test the model wrote never sees the key its step was
  handed.
- a spent balance (`Credit balance is too low`) or a spend limit the
  account set parks the run as a provider outage, resumable with
  `--resume` once the balance is topped up, never a failed step
  (`journal.md`, "why a run stopped").
- an `sk-ant-` key in an answer, an error or a gate's output is made
  `sk-ant-REDACTED` before the run reads it, and in every recording and
  record file (`journal.md`, "what gets written"); so is the exact value a
  key file handed in this process, whatever its shape (a gateway's bearer
  token, a proxy's key). a key file holding fewer than 20 characters is
  refused before the step's call: every key shape known here is far longer,
  and a value that short is a word often enough that redacting it would blank
  it out of every later line of the process, while leaving it unredacted
  would write a secret into the record.

the prompt cache: on a subscription the cli asks for the hour-long cache on
its own; on an api key it asks for 5 minutes unless told otherwise, and a
step that waits longer than that between its goes (a gate, a sibling, a
person) reads its whole prompt again at the uncached rate. so an `api-key`
connector's call is started with `CLAUDE_CODE_PROMPT_CACHE_TTL=1h`. the
api bills an hour's cache write above a 5-minute one; the hour keeps runs on
the key comparable with runs on the subscription. the **api** provider marks
a carried-on step's prompt with the hour lifetime itself (above).

### what is not supported yet

- other provider families. every connector today reaches one family: the
  `claude` cli on a login or a key, the http api, or the stub. a step cannot yet pick
  a model of another family, and no provider declares its capabilities; a
  later provider that lacks a feature is meant to say so loudly, never to
  drop it.
- taking a key helper out. `subscription` takes the key and token
  variables out of the environment, but an `apiKeyHelper`, an `env` block in
  the operator's own settings file (which every step but one that only looks
  loads, `--setting-sources user`), a saved Console key or a profile still ranks
  above the subscription login in the cli; such a step is refused before its
  call (above), never run on it.
- a key's shape. any text of 20 characters or more in the key file is
  handed over as the key; the cli says if it is wrong. the redaction knows
  the `sk-ant-` shape and the values this process handed; a key exported in
  your shell under `inherit` is redacted only when it has the `sk-ant-`
  shape.
- which key paid. `auth_method: api_key` says the cli used an api key, not
  which one: an `env` block setting `ANTHROPIC_API_KEY` in your own settings
  file can replace the key the step was handed (the cli applies such a block
  over the environment it starts with), and the cli prints no key id. the
  step line's `claude-api:api-key` is the credential agentweft handed; the
  Console's usage page for the key is the truth of what paid.
- the gates take provider credentials out by name: a key copied into a
  variable of another name reaches them.

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

    python run.py code-review --force --task-file change.diff --model-for reviewer=low,worker=opus

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
act on it (`docs/journal.md`). `python run.py step` takes `--model-for` and
`--effort-for` the same way, so one step can be tried on another model or
level without a copy of the flow.

## how hard the model thinks

a tier picks a model; it can also pick how hard that model thinks. the levels
are `low`, `medium`, `high`, `xhigh` and `max`, the words both the cli's
`--effort` and the api's `output_config.effort` take, and they live in the
environment beside the model ids:

    EFFORT_LOW=low
    EFFORT_HIGH=high
    EFFORT=...         the one level when a tier has nothing of its own

an `effort` named inside a `provider:` block wins over both. a role or a step
can name its own level, in the same three places a model is named:

    python run.py fix-with-test --force --effort-for reviewer=high

    efforts:
      reviewer: medium

    steps:
      - role: worker
        prompt: worker.md
        effort: low

highest first: `--effort-for`, the step's `effort:`, the flow's `efforts:`,
then the provider's own (its block, `EFFORT_<TIER>`, `EFFORT`). a level that is
not one of the five is refused before anything is asked, and a resumed run
keeps the levels it was started with. `runs/<id>/efforts` is read the same
way on a resume: a level edited into it that is not one of the five is
refused, not handed to the cli.

nothing set anywhere is the default, and then nothing is sent: no `--effort`,
no `output_config`, and the provider's own default answers (on the cli that
is its own resolution - `CLAUDE_CODE_EFFORT_LEVEL`, its settings, then the
model's default, which is `medium` on the current Opus).

**a step sent back thinks harder.** every time the work goes back to a step -
a failed gate sending the step itself again, a verdict of `redo` sending it to
the step before, a step calling a test wrong sending it to the step that wrote
the test - that step's next go is asked one level above its previous one,
counted from its own base, and up to `xhigh` and no further. `max` is only
ever run when it is named. each step counts its own send-backs, so one step
going round twice never raises another, and the count is kept in the run's
`manifest.json`, so a step sent back and then stopped carries on one level up
after `--resume`. a step with no level set anywhere is
not raised: the provider's default is not a level this can count up from.
every line in `steps.jsonl` says which level that go was asked at, the base
it was raised from and how many send-backs raised it (`journal.md`).

`claude` gets the level as `--effort <level>` (checked against
`claude --help` and the cli reference for 2.1.296). the cli ranks its
`CLAUDE_CODE_EFFORT_LEVEL` beside `--effort` without saying which of the two
wins, so a call that names a level starts without that variable. a command
other than `claude` and **fake** carry the level and do not act on it.

the **api** provider sends `"output_config": {"effort": <level>}`. thinking is
spent inside `max_tokens`, so with no `max_tokens` in the provider block the
cap is 64000 at `high` and above and 32000 otherwise. it sends the
`anthropic-version` header with every request.

**a terse step answers under a quarter of that default cap**: 8000, or
16000 at `high` and above. the api sends it as `max_tokens`, unless the
provider block names a lower one. `claude` has no flag for it and gets
`CLAUDE_CODE_MAX_OUTPUT_TOKENS`, unless the run's environment already holds a
lower one; that variable caps every model turn of the step, tool calls
included, not only the last answer. a command other than `claude` and
**fake** get no cap, and the step's line says so (`journal.md`).

an answer cut off at its cap is not a whole answer, and neither is a model
declining to answer, though both come back with a 200: `stop_reason`
`max_tokens` or `refusal`, on the api's response and on `claude`'s json
result alike, fails the step with that reason, and keeps the usage the
attempt was paid for.

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
- `--permission-mode dontAsk`, always passed, because the mode a `-p` run
  starts in otherwise depends on the host. `AGENTWEFT_PERMISSION_MODE` (which
  `agentweft init` asks for) names another of `claude`'s modes; any mode but
  `dontAsk` stops the denial above from covering what the grant left out.
- `--strict-mcp-config` and `--disallowedTools "mcp__*"`: `--tools` does not
  reach MCP tools, so the place's `.mcp.json` is not loaded and no MCP tool is
  left.
- `--disable-slash-commands`, no skills or commands.
- for a grant that only looks (no `write`, `edit` or `shell`), `--restricted`:
  the command and code running tools and WebFetch are gone unless `--tools`
  names them, the file tools stay inside the working directories, and no user,
  project or local settings file is read. so a model the operator's own
  settings file names (`model` in `~/.claude/settings.json`, or under
  `CLAUDE_CONFIG_DIR`) would not reach it, and it would run on the cli's
  default while every step that acts runs on that model: such a step is
  passed it as `--model`, unless the flow or `MODEL` named one already or
  `ANTHROPIC_MODEL` is set, which the cli reads itself. a cloud route that
  file switches on reaches it in the environment ("what the command's
  process holds").
- for a grant that acts, `--setting-sources user` (below).

a step that says it writes and names no `tools:` is granted what that needs
(`flows.md`, "what a step writes"): `writes: tests` and `writes: product`
get `read, grep, write, edit, shell`, `writes: spec` gets `read, grep, write,
edit`. so a working step runs under the fence and `dontAsk` on any host, a
new install whose cli denies writes in `-p` included.

a step with no grant gets none of the fence: one with no `tools:` that says
`writes: none` or nothing about what it writes. the host's own defaults
decide its tools and what it may write (for an operator whose settings say
`acceptEdits` and an allow list, those; for a new install, the cli's default,
which denies writes in `-p`). it is started with `--setting-sources user`
too.

### what a place may hand the cli

in `-p` the cli shows no trust dialog, and on a folder nobody trusted it
still runs the project's settings hooks, applies its `env` block, runs its
`apiKeyHelper` and other helper commands, a project skill's hooks, and
connects every server in its `.mcp.json` without asking (the cli's
permissions reference, "What runs before you trust a folder", whose first
remedy is this flag). a place is a folder a clone or a step wrote, never the
person, so every `claude` step, granted or not, loads only the user source:

- `--setting-sources user` on every step that acts or has no grant;
  `--restricted` on a step that only looks reads no settings file at all.
- what still loads: your own settings file under `~/.claude` or
  `CLAUDE_CONFIG_DIR` (its hooks, `env`, `apiKeyHelper`, user-scope MCP
  servers, your skills) and your organisation's managed settings. those are
  yours.
- what never loads from the place: `.claude/settings.json`,
  `settings.local.json`, their hooks, `env` and helpers, `.mcp.json`, project
  skills, commands and subagents, and the instruction files the cli read
  from the project source.
- the instruction files come back as text: when the run starts, the place's
  root `CLAUDE.md`, `.claude/CLAUDE.md` and every `.md` under
  `.claude/rules/` are read once, in that order, each under its path, into
  `<run>/brief/place.md` beside the run's record, and every `claude` step in
  the run is passed it with `--append-system-prompt-file` (appended to the
  cli's own system prompt). a file that cannot be read is named there as
  `unreadable: <path>`, and the step still runs. a place with none of them
  passes no such flag.
- what a step wrote to one of those files after the start is not handed:
  the brief is the start's, and the briefing guard (`guardrails.md`) refuses
  a step whose model would start after one changed.
- not handed, and not loaded either: `AGENTS.md` (the cli never read it),
  `CLAUDE.local.md`, and a `CLAUDE.md` in a subfolder, which the cli loaded
  when a tool opened a file under it. a step may still Read any of them.

`--settings '{"disableAllHooks":true}'` is not passed on purpose: it would
turn off a hook the run hands over itself. the opposite is: whenever the run
hands a step a hook, granted or not, its `--settings` carries
`"disableAllHooks": false`, and the command line sits above the user
settings file, so your own settings cannot switch the run's hook off either.
managed settings sit above the command line, so `allowManagedHooksOnly` or a
managed `disableAllHooks` still can, and the run cannot tell. `--bare` is
not passed either: it authenticates only by API key.

the floor is `claude` 2.1.295, the first release in which `--tools` and
`--restricted` also apply to the built-in tools that register after launch;
below it the fence fails open. so a step with a grant asks `claude --version`
once and is refused before it starts, with the version in the reason, when the
cli is older or says something that is not a version. a step without a grant
that works in a place carries the run's hook, and is held to the same floor:
refused, with the version in the reason, when its version reads older; when
the version does not read, it runs, and its line says `shell_writes_denied:
null` with `shell_writes_unchecked: "not checked: cli version unread"`
rather than a count of 0 the run could not stand behind. a step without a
grant and no place carries no hook and is not held to it.

the step's line in `steps.jsonl` keeps the grant, every flag it became (the
command line minus the command; the prompt is on stdin) and the version
(`journal.md`).

### a shell step writes files with the write tool

a `shell` grant is Bash and PowerShell, and both can write any file. that is
where the turns go: a heredoc turns the `\n` escapes it carries into real
newlines, a `sed` that matches nothing changes nothing and says nothing, a
script run on Windows flips every line end in the file, and each costs the
step turns to notice and undo. the Write and Edit tools have none of those.

so a `claude` step granted `shell`, and one in a place granted nothing (it
has every tool, the shell among them), is also handed a PreToolUse hook on
Bash and PowerShell in its `--settings`, next to the attribution setting
below:

    {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell",
      "hooks": [{"type": "command", "command": "<python>",
                 "args": ["-I", "<agentweft>/guardrails/shellwrite.py",
                          "runs/<run-id>/tool-denials.jsonl"]}]}]}}

`args` is the exec form: python is spawned with no shell between, so nothing
is quoted differently by platform, and `-I` keeps the script's own folder off
its import path. permission rules cannot do this job, since they match a
command by its prefix and "Bash, but not the Bash that writes" has none.

the hook reads the command and exits 2, which the cli takes as a refusal and
shows the model, for a redirect or a heredoc into a file (`/dev/null`, a
duplicated descriptor such as `2>&1`, the temp dir and the run's own
`runs/<run-id>/tmp/` excepted; the temp dir and the place are compared by
their real paths, so a temp dir reached through a link, as macos's is, counts
whichever way it is spelled), `tee`, `cp`,
`mv` and `install`, `sed -i` and `perl -i`, `dd of=`, `truncate`, a
`python -c` or python heredoc that opens a file to write or calls
`write_text`, and PowerShell's `Set-Content`, `Add-Content`, `Out-File` and
`WriteAllText`. the reason names Write and Edit, and a step that cannot make
the change with them says so on a `NEEDS:` line. it reads each command a
`$(...)` or backquotes run as well, and the command a shell is handed by
`-c` or a heredoc (`bash -c '...'`, `sh <<EOF`). it reads quotes as the
shell does, so a `\"` inside double quotes, a `$'...'` or a quote inside a
substitution never turns a read into a refusal, a `<<` inside quotes or an
arithmetic `$((...))` opens no heredoc, an arithmetic `$((3 > 2))` writes
nothing, and operators written together (`;>`, `)>`) are read one by one.
a command `eval` builds and a script file a shell runs are not read. a call
it cannot read (a quote left open, input
that is not a call) and an error of its own are refused too: a check that
crashes and lets the call through is no check. it catches the shell's write
syntax and the programs whose job is writing, not every program that writes a
file on the way to something else.

each refusal is one json line in `runs/<run-id>/tool-denials.jsonl`, with the
session, the tool, the command and the part that writes; a call it could not
read has an empty part that writes and `unread` with the error's kind. the
step's line in
`steps.jsonl` counts its own as `shell_writes_denied`, and counts as
`shell_trap_recoveries` the model's messages in its transcript that name one
of the three traps above (`journal.md`).

a `claude` step in a place granted `write` or `edit`, or granted nothing
(which has every tool), gets the same hook on Write, Edit, MultiEdit (an
older name the cli still maps onto Edit) and NotebookEdit, added to the
matcher, with `--keep <place>/decisions.md`, `--keep-all <place>/.git` and
`--place <place>` among its `args`. for those tools it reads `file_path`
(`notebook_path` for NotebookEdit) and refuses a call on a kept file, so a
step cannot write the ruling that lets its own change stand ("the rulings
only the runner writes" in `guardrails.md`), a call on the place's `.git`
or anything under it (its config and hooks run as you on agentweft's next
git, `gates.md`), and a call outside the place and outside the run's own
`runs/<run-id>/tmp/` ("the scope fence" in `guardrails.md`); every other path goes
through. a step in no place, or granted tools that hold neither `shell` nor
`write` nor `edit`, gets no hook.

a `claude` step in a place with facts (`journal.md`, "what is known about a
file") is also handed a PostToolUse hook on Read, Edit and Grep, beside the
other hooks in the same `--settings`:

    {"hooks": {"PostToolUse": [{"matcher": "Read|Edit|Grep",
      "hooks": [{"type": "command", "command": "<python>",
                 "args": ["-I", "<agentweft>/guardrails/factsread.py",
                          "<place>", "runs/<run-id>/facts-index.json",
                          "runs/<run-id>/facts-read.jsonl",
                          "--handed", "F-0001,F-0002"]}]}]}}

the runner writes the place's live and stale facts to `facts-index.json` when
the run's folder is made. after a call on one file of the place, the hook
prints the facts that hold for it as the call's `additionalContext`, which
the cli hands the model with the result: nearest first, at most 1500
characters, once a file a session, never one the step's brief handed
(`--handed`) or one handed on an earlier file, never a project-wide one, each
without its anchored lines (the step has the file open). each lookup is a
line in `facts-read.jsonl` (session, file, ids), and the ids handed join the
brief's on the step's `facts_attached`. a call the hook cannot read hands
nothing and stops nothing. a `--restricted` call loads `--settings` too
(`claude --help`), so a step that only looks gets the hook as well; a call
that keeps a cache warm, and the retro, get none.

the step is told both halves in its prompt: that a shell write is refused, and
for a step granted `write` or `edit`, one known trap of those tools: they
store the characters they are given, so a U+2028 or U+2029 meant as an escape
has to be written as its backslash form.

the hook can be switched off from outside the run only by managed settings:
the run passes `"disableAllHooks": false`, which wins over the user, project
and local files, but a managed `disableAllHooks` or `allowManagedHooksOnly`
can still block it, and the run cannot tell. a command other than `claude` is handed no
hook, and its grant records `shell_writes` as `not enforced`.

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

or every run takes it from `AGENTWEFT_CO_AUTHOR=true` in `.env`, which
`agentweft init` asks about (off unless you say yes). either way the
attribution setting is then left out of `--settings`, so the cli's own default
answers. a provider block that says `co_author: false` wins over the `.env`
line.

### the model switch

when the cli's safeguards flag a message, its default is to answer it with
another model in the same call: the transcript holds a `system` record with
subtype `model_refusal_fallback`, the turns after it carry the other model in
`message.model`, and the call ends as if nothing happened. the settings
schema of `claude` 2.1.309 documents the key that decides it,
`switchModelsOnFlag`: "When safeguards flag a message, automatically switch to
a different model to keep chatting. When off, your session will pause
instead." every `claude` call here is handed `"switchModelsOnFlag":false` in
its `--settings`, so a step's answer is the model it asked for or none: a
refused call ends on the refusal, which the step reads as its error
(`stop_reason refusal` is `the model declined to answer`) and the run stops
there like any other provider error. how a refused `-p` call prints with the
key off was read from the cli's bundled code, not seen on a run.

a subagent a step starts inside its own call is not held by the key in that
code: its fallback is local to its own reply. so the runner still reads every
step's transcript for the fallback (`journal.md`, `fallback`), and a step
another model answered is never taken quietly: the console prints `<step> was
answered by <model>, not <asked>: the provider switched models; its output is
that model's` when the step ends, the handoff's run section opens with the
same line, and a flow with `on_fallback: park` parks the run there for a
person before a later step takes that output (`writing-a-flow.md`).

### the runaway guard

every `claude` call that may use a tool is started with `--max-turns 50`,
which the cli's reference describes as a limit on agentic turns, print mode
only, ending the call with an error at the limit. it is there to stop a step
caught in a loop, not to ration one: a budget is `max_calls` and, on the
api, money. a call stopped there comes back with the subtype
`error_max_turns`, is not gone again, and the step fails with "still calling
tools at --max-turns 50, the runaway guard (max_turns)", so the run stops on
it with its tokens counted. the number is set in the provider block or from
`AGENTWEFT_MAX_TURNS` in `.env`; `0` takes the limit off, and anything but a
whole number is refused when the run starts:

    provider:
      provider: cli
      max_turns: 80

a keep-warm call uses no tool and is started without it, and a command other
than `claude` is never handed it.

### what the command's process holds

a model step can be pointed at a repo you did not write, so the command does
not inherit the run's environment. it starts with what any process needs to
start and find its home folder (`PATH`, `HOME` or `USERPROFILE`, `TEMP`, the
locale, `SYSTEMROOT` and friends on Windows), the proxy and certificate names
(`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `NODE_EXTRA_CA_CERTS`,
`SSL_CERT_FILE`), and nothing else. a token in the shell, a cloud key, the
api provider's `API_KEY` and whatever `.env` loaded stay with the runner.

`claude` also gets every name under `ANTHROPIC_` and `CLAUDE_`, because that
is where it reads its own login and settings: `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CONFIG_DIR`,
`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK` and the rest. a subscription
login lives in the cli's config folder, not the environment, so it keeps
working. any other command gets none of those: its login is not ours to
guess. the same environment answers `--version` and `claude auth status`, so
the check says what a step will see.

`claude` on a cloud route also gets the names that route finds its login
and region by, as the cli's own page for each route names them, and only
while the route's switch is on (the cli reads a switch as on for `1`,
`true`, `yes` or `on`):

- `CLAUDE_CODE_USE_BEDROCK`, `_MANTLE` and `_ANTHROPIC_AWS`: `AWS_PROFILE`,
  `AWS_REGION`, `AWS_DEFAULT_REGION`, `AWS_CONFIG_FILE`,
  `AWS_SHARED_CREDENTIALS_FILE`, `AWS_CA_BUNDLE`.
- `CLAUDE_CODE_USE_VERTEX`: `GOOGLE_APPLICATION_CREDENTIALS`,
  `CLOUDSDK_CONFIG`, `CLOUD_ML_REGION` and the cli's `VERTEX_REGION_CLAUDE_*`
  names, each listed (`cli_provider.ROUTES`).
- `CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD`: `GOOGLE_APPLICATION_CREDENTIALS`,
  `CLOUDSDK_CONFIG`.
- `CLAUDE_CODE_USE_FOUNDRY`: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
  `AZURE_AUTHORITY_HOST`, `AZURE_FEDERATED_TOKEN_FILE`,
  `AZURE_CLIENT_CERTIFICATE_PATH`, `AZURE_CONFIG_DIR`.

each of those says where the login lives (a profile, a region, a file, a
host), never a secret: an access key, a session token, a bedrock api key or
a client secret is not handed by a route. a step that acts loads your
settings file and its `env` block itself; a step that only looks starts
`--restricted` and reads no settings file, so a route switched on in that
block alone, or one whose profile and region live only in the run's
environment, would reach it with no profile and no region to log in by. so
the switch of every
route and a switched-on route's names are read from your own settings
file's `env` block first, then the run's environment, the way the cli
writes that block over the shell's values; an empty switch there turns a
shell's route off. nothing else of the block is handed: not a model, not a
key helper, not a key.

a name the command needs beyond that is listed in the provider block in the
flow (a connector `project.yml` declares may not list one):

    provider:
      provider: cli
      env: [AWS_PROFILE, AWS_REGION]

or once for every step of every flow in `AGENTWEFT_PROVIDER_ENV`, comma
separated, the names a flow shipped by someone else cannot know (a route's
key, a proxy token). it is yours to set: a `.env` inside the place is
refused it, as it is a key file. a secret your route logs in with reaches a
step only this way, and only from the run's environment: one kept only in
your settings file's `env` block reaches the steps that act (the cli loads
the file) and not the ones that only look.

all of this is `auth: inherit`. a connector's `subscription` or `api-key`
then takes the credentials out as under "connectors", a listed name
included.

the cli keeps a route's names for the model's own shell: its subprocess
scrub (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`, on for every connector's step)
removes a variable whose name or value looks like a credential, and a
profile, a region or a file path does not. so a step's shell can reach the
same cloud profile the cli does.

`--bare` would fence the cli harder, but it reads only `ANTHROPIC_API_KEY` or
a key helper and never the subscription login, so it is not passed.

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
(`claude auth status --json`, started in the place with the step's
environment, by its exit code and its `authMethod`; the account is never
printed), the model a step would ask for, or the cli's default, and
the effort level, or that the cli's own answers. a
version below the floor fails the check, because every shipped reviewer
carries a grant and would be refused. neither question makes a model call.
