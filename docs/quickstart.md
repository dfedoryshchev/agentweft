# quickstart

from a clone to a green run, then to a real task. the first two steps need no
key and cost nothing.

## 1. install it and answer init

    pip install -e .
    agentweft init

run these from the top of the clone. `-e` keeps the run records in `runs/`
beside `run.py`, where `rollup.py` and the mcp server read them; a plain
`pip install .` writes them inside the installed package instead. the flows
and the examples are read from the directory a command starts in, and so is
`.env`.

`init` asks the few things a run needs and writes them to `.env`, where every
run reads them:

- the provider a flow that names none runs on: `cli` shells out to `claude`,
  `api` is the http one
- a model per tier, `MODEL_HIGH`, `MODEL_MID` and `MODEL_LOW`: an alias such
  as `opus` or `sonnet`, or a full id. blank writes no line, so one set in the
  shell still counts; with none it falls to `MODEL`, then to the provider's
  own default
- the permission mode a step with a tool grant runs `claude` in, `dontAsk`
  unless you say otherwise: anything the grant did not allow is denied
- whether to keep the attribution trailer `claude` adds to its commits and
  pull requests. off unless you turn it on
- the caps a run parks at, `max_calls` and `max_tokens`, for a flow that sets
  none
- whether coding flows may write end-to-end tests. the recommendation is no:
  they are slow and want a running system
- what a run commits: `none` leaves every change in the work tree, `wip`
  commits after each step, `squash` makes one commit per task
- the files that are the spec, as globs from the top of the project
- whether to keep a price table of your own, `prices.yaml`. one already
  there is never written over, `--force` or not. a run reads it only when
  agentweft starts outside the run's place and its repo, or when `PRICES` in your
  environment names it (`guardrails.md`, "what it cost in money")

`agentweft init --yes` takes every default and asks nothing. an `.env` that is
already there is left alone; `--force` rewrites the keys init asks about and
keeps the rest. the settings are `AGENTWEFT_<KEY>` lines: edit `.env`, or set
the same name in the environment and leave it out of `.env`, which wins when
both have it. a flow file that sets `max_calls`, `max_tokens` or `tests_e2e`
itself wins over either.

`.env` is read in the folder agentweft starts in. when that folder is the
place the run works on, inside it, or anywhere in the git repo the place is
in (the root above a `--workdir packages/app`), the `.env` is the project's
file (a clone ships one, a step can write one), and it may set only:

- the preferences: `AGENTWEFT_TIMEOUT`, `_RETRIES`, `_WORKERS`,
  `_TESTS_E2E`, `_TESTS_INTEGRATION`, `_SPEC_GLOBS` (`project.yml`'s `spec:`
  is the project's too), `MODEL`, `MODEL_<TIER>`, `EFFORT`, `EFFORT_<TIER>`,
  `PYTHONIOENCODING`
- any other of agentweft's own settings at what the run would have used
  anyway (the value in your environment, else the default), or a cap tighter
  than that: `agentweft init --yes` in the project folder writes the
  defaults there, and the quick start runs on them
- the names `env:` in `project.yml` declares (the variables the project's own
  tests read, `orchestrate.md`): those reach the gates that run the tests,
  never agentweft's own environment, its git or the model's process

anything else refuses the run before any process starts, with the file and
the name: a looser guard, a credential or where one is sent, `PATH`, a home
folder, a proxy, every `GIT_*`, `PYTHON*`, `LD_*` and `DYLD_*` name,
`NODE_OPTIONS`, `BASH_ENV`, and any name agentweft does not read and
`project.yml` does not declare. a line that is not `NAME=value` refuses too.
the place is the folder `--workdir` names, else the one agentweft starts in
(a place a flow file or a carried-on run names is not known that early, so
a `.env` beside you is read as the project's). a `.env` in a folder of your
own, outside the place and outside its repo, is yours: every name in it is
applied. so keep the
rest in your shell, or run agentweft from a folder of your own with
`--workdir`.

it ends by printing the next two commands. installed with `-e` and run
anywhere else, it adds `--flows` and the clone's folder to each, so both work
from there.

## 2. a green run, without a model

    agentweft minimal --force --flows examples

the examples use the `fake` provider, which replays canned text, so this works
on a fresh clone with nothing set up. it ends on `done`. `two-step` and `watch`
are the other two; run `two-step` to watch work get sent back for a redo.

    agentweft list
    agentweft show minimal --flows examples

print the flows and what one promises. every command reads `--flows`, and
`agentweft` with nothing after it prints the help.

## 3. a real task

    agentweft provider

says whether each configured provider is usable, without spending anything.
then point a coding flow at your project with what you want done:

    agentweft fix-with-test --workdir ../my-project --task "add(1, 2) returns -1"
    agentweft build-feature --workdir ../my-project --task-file spec.md

`fix-with-test` writes a failing test for the bug, then the patch.
`build-feature` writes the failing tests for a spec, then the code. a flow
says where the task goes by writing `{TASK}` in its own words; one that has no
`{TASK}` refuses a task, and one that has it will not start without one.
`docs/flows.md` has the rest.

## 4. when it stops halfway

    agentweft fix-with-test --resume

picks up the last run of that flow from its own manifest, so the steps that
already succeeded are not paid for twice.

to work on one prompt without running the flow around it:

    agentweft step fix-with-test worker --workdir ../my-project

that reads stdin, writes nothing down, and prints what came back.

## 5. what it cost

    agentweft spend

the last runs, one line each, then the same runs per flow and per provider:
tokens, the money the price table gives them, and what the provider said they
cost. the table is `agentweft/guardrails/prices.yaml`, dated; `PRICES=<path>`
in your environment, or a `prices.yaml` where you run when that folder is
neither the run's place nor in its repo, wins over it. `python rollup.py` is the wider view, and takes
`--flow x` and `--failed`.

## next

- `docs/writing-a-flow.md` - adding your own
- `docs/gates.md` - checks that are programs, not prompts
- `docs/guardrails.md` - spend caps and promises
- `docs/providers.md` - what the `cli` provider hands `claude`
