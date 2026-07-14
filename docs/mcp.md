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
- `flows://run/<run-id>` - every step of one run, concatenated

**tools**

- `run_flow(flow)` - runs it with `--force` and returns what it printed

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

before the planner runs, the client starts that server, calls the tool, and
appends the answer to the planner's prompt. for repo-audit that is a ranking of
which files are risky to touch, so the plan comes out ordered by blast radius
instead of by whatever got read first.

it is advisory on purpose. if the server is missing or slow the run says so and
carries on - a flow does not fail because a side channel is down.

nothing in here knows which tool it is talking to. anything speaking the same
protocol works.

## preflight

the risk map is advisory by default: it goes into the planner's prompt and the
planner weights by it, mostly. a step can be made to check rather than trust:

    steps:
      - role: worker
        prompt: worker.md
        preflight:
          mode: flag       # or refuse
          threshold: 0.7

before the run moves on, the files the step said it would touch are checked
against the ranking. `flag` prints them and carries on. `refuse` stops the run
and writes `refused at <step>, hot blast radius` to the journal.

this is the part that is not a prompt. asking an agent to be careful about a
hot file is a prompt. a number and a comparison is a control.

it needs a `context:` block on the flow, because without a ranking there is
nothing to check against, and with no ranking nothing is ever flagged.

## it is hand rolled

about a hundred lines of dict handling over line delimited json. i have twice
now added a dependency to avoid writing something this size and twice taken it
back out. when an official sdk settles down this is a small thing to swap.
