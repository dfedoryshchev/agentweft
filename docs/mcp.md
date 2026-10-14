# mcp, both directions

this repo is on both ends of the protocol: a server so an agent can read what
the flows did, and a client so a flow can ask something else what it knows.

# the server

    python mcp_server.py

stdio json-rpc. point a client at it and it can read the journal and the run
outputs, and start one of a small list of flows.

## what it exposes

**resources**

- `flows://journal` - the run journal
- `flows://run/<run-id>` - every file one run left, its per-pass step files
  and `steps.jsonl` included, concatenated

**tools**

- `run_flow(flow, task?)` - runs it with `--force` and returns what it printed.
  a run that did not finish leads with what its exit code means: it could not
  start (1), it stopped before the end (2, the journal says why), or it was
  interrupted (130). a `task` goes to the run as a UTF-8 `--task-file`,
  deleted once the run ends (`runs/<id>/task.md` keeps it). a flow that takes
  a task and got none, or got one it has no place for, answers with run.py's
  one-line refusal

## the allowlist

`ALLOWED` in `mcp/server.py` is the list of flows the tool will start. it is
short on purpose. repo-audit has a twenty six call ceiling and an agent that
can start it in a loop is a bill, not a feature.

reading is unrestricted. reading is the half i actually use.

# the client

a flow can name a tool server it wants context from:

    context:
      command: ["some-tool", "mcp"]
      tool: hotspots
      arguments: {dir: "."}

before the planner runs, the client starts that server, calls the tool, and
appends the answer to the planner's prompt. for repo-audit that is a ranking of
which files are risky to touch, so the plan comes out ordered by blast radius
instead of by whatever got read first.

`arguments` go to the tool as they are written. the server runs in the run's
`workdir` (see `docs/flows.md`), so a relative `dir` means the directory the
run works on. before the call the client reads the tool's schema from
`tools/list`, and an argument the schema requires that the block leaves out is
named, rather than sent: a server is not obliged to refuse that call, and one
that ranks the files under a `dir` it was never given ranks nothing and answers
with an empty list, which reads exactly like a codebase with no risk in it.

it is advisory on purpose. if the server is missing or slow, does not have the
tool, is missing an argument, answers with nothing, or says the tool failed, the
run prints `no risk map:` and why, and carries on - a flow does not fail because
a side channel is down. a step with a `preflight:` set to `park` or `refuse`
still parks when its turn comes, because it has nothing to check against
(below).

nothing in here knows which tool it is talking to. anything speaking the same
protocol works.

## preflight

the risk map is advisory by default: it goes into the planner's prompt and the
planner weights by it, mostly. a step can be made to check rather than trust:

    steps:
      - role: worker
        prompt: worker.md
        preflight:
          mode: flag       # or refuse, or park
          threshold: 0.7

before the run moves on, the files the step said it would touch are checked
against the ranking. `flag` prints them and carries on. `refuse` stops the run
and writes `failed at <step>` to the journal, with the cause `refused` and the
why `hot blast radius: <files>`. `park` stops it
the way a `pause:` does: the step's output stays in `runs/<id>/<step>`, the
handoff names each hot file with its score, the step's line in `steps.jsonl`
says `parked`, the journal says `parked at <step>`, and `--resume` carries on
after that step with whatever that file holds by then. so a person owns the
risky edit, rather than the agent making it or declining it. any other `mode`
is refused when the flow loads.

the same check runs first on what the step is handed - the plan, or whatever
the step before it produced - before the step is called. a step that can edit
files has already edited them by the time its answer is checked, so a plan that
names a hot file stops the run there instead. `flag` prints
`preflight: <step> was handed <n> hot file(s)` and the step runs. `refuse`
stops the run the same way as above without spending the call. `park` stops it
before the step: the handoff says `stopped before <step>`, the manifest keeps
the step as not run, and `--resume` starts AT that step, on what it was handed.
carrying on is the go-ahead: the step is not checked again on the files the
plan named, and the check after it stops only on a hot file that was not among
them. to change what the step works from, edit what the step before it
produced first, the way any handed file is edited.

the check on the handed text only sees the files the plan names. a file the
model decides on mid-step is not in it, so the check after the step, and the
fence on what actually changed (`docs/guardrails.md`), still report that one.

this is the part that is not a prompt. asking an agent to be careful about a
hot file is a prompt. a number and a comparison is a control.

it needs a ranking, which comes from the flow's `context:` block when the
planner runs. no ranking is not the same as nothing hot, and the step says so:
the server was down, it answered with something that is not `path score`
lines, the flow has no `context:` block, or a `--resume` picked the run up past
the planner, so the map was never fetched. in each case the run prints
`preflight: no ranking to check against, <step> not checked` once, before the
step. `flag` carries on after that line. `park` and `refuse` both park before
the step runs, with the why `<step> was not checked: no ranking to check
against`: a step set to stop on a hot file is not let through on a check that
never ran, and refusing it would claim a blast radius nobody measured, so a
person reads it and carries on with `--resume`, which runs the step and does
not stop it again for the same missing map. the map itself stays advisory - a
planner without one still runs. a `preflight:` on the planner itself is checked
only after it, since the planner is the step that fetches the map.

a `command` gate reads the same ranking to pick between a short test command
and a long one (`docs/gates.md`).

## it is hand rolled

about a hundred lines of dict handling over line delimited json. i have twice
now added a dependency to avoid writing something this size and twice taken it
back out. when an official sdk settles down this is a small thing to swap.
