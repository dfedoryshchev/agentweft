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

## it is hand rolled

about a hundred lines of dict handling over line delimited json. i have twice
now added a dependency to avoid writing something this size and twice taken it
back out. when an official sdk settles down this is a small thing to swap.
