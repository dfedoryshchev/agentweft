# providers

a provider answers a prompt. that is the whole interface:

    ask(prompt, timeout) -> Reply(text, detail, usage, cost, session, model, retryable)
    check() -> (ok, detail)

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
  thing that rots quietly and then surprises you. a step with `continue:
  resume` is sent its earlier messages and answers with the new prompt, the
  new prompt marked `cache_control` with the hour lifetime (`"ttl": "1h"`);
  the messages live as long as the process.
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
  project or local settings file is read. so a model the person's own
  settings file names (`model` in `~/.claude/settings.json`, or under
  `CLAUDE_CONFIG_DIR`) would not reach it, and it would run on the cli's
  default while every step that acts runs on that model: such a step is
  passed it as `--model`, unless the flow or `MODEL` named one already or
  `ANTHROPIC_MODEL` is set, which the cli reads itself.
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

### a shell step writes files with the write tool

a `shell` grant is Bash and PowerShell, and both can write any file. that is
where the turns go: a heredoc turns the `\n` escapes it carries into real
newlines, a `sed` that matches nothing changes nothing and says nothing, a
script run on Windows flips every line end in the file, and each costs the
step turns to notice and undo. the Write and Edit tools have none of those.

so a `claude` step granted `shell` is also handed a PreToolUse hook on Bash
and PowerShell in its `--settings`, next to the attribution setting below:

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
duplicated descriptor such as `2>&1` and the temp dir excepted), `tee`, `cp`,
`mv` and `install`, `sed -i` and `perl -i`, `dd of=`, `truncate`, a
`python -c` or python heredoc that opens a file to write or calls
`write_text`, and PowerShell's `Set-Content`, `Add-Content`, `Out-File` and
`WriteAllText`. the reason names Write and Edit, and a step that cannot make
the change with them says so on a `NEEDS:` line. a call it cannot read, and
an error of its own, are refused too: a check that crashes and lets the call
through is no check. it catches the shell's write syntax and the programs
whose job is writing, not every program that writes a file on the way to
something else.

each refusal is one json line in `runs/<run-id>/tool-denials.jsonl`, with the
session, the tool, the command and the part that writes. the step's line in
`steps.jsonl` counts its own as `shell_writes_denied`, and counts as
`shell_trap_recoveries` the model's messages in its transcript that name one
of the three traps above (`journal.md`).

a `claude` step granted `write` or `edit` gets the same hook on Write, Edit,
MultiEdit (an older name the cli still maps onto Edit) and NotebookEdit,
added to the matcher, with `--keep <place>/decisions.md` among its `args`.
for those tools it reads `file_path` (`notebook_path` for NotebookEdit) and
refuses only a call on a kept file, so a step cannot write the ruling that
lets its own change stand ("the rulings only the runner writes" in
`guardrails.md`); every other path goes through. a step granted neither
`shell` nor `write` nor `edit` gets no hook.

the step is told both halves in its prompt: that a shell write is refused, and
for a step granted `write` or `edit`, one known trap of those tools: they
store the characters they are given, so a U+2028 or U+2029 meant as an escape
has to be written as its backslash form.

the hook can be switched off from outside the run: `disableAllHooks` in the
user's own settings is not overridden here, and `allowManagedHooksOnly` in
managed settings can block it, and the run cannot tell. a command other than `claude` is handed no
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
`agentweft init` asks about (off unless you say yes). either way `--settings`
is then not passed at all, so the cli's own default answers. a provider block
that says `co_author: false` wins over the `.env` line.

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

a name the command needs beyond that is listed in the provider block, for
example the cloud credentials a Bedrock or Vertex login reads:

    provider:
      provider: cli
      env: [AWS_PROFILE, AWS_REGION]

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
(`claude auth status`, by its exit code and its `authMethod`; the account is
never printed), the model a step would ask for, or the cli's default, and
the effort level, or that the cli's own answers. a
version below the floor fails the check, because every shipped reviewer
carries a grant and would be refused. neither question makes a model call.
