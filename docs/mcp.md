# the mcp server

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

## it is hand rolled

about a hundred lines of dict handling over line delimited json. i have twice
now added a dependency to avoid writing something this size and twice taken it
back out. when an official sdk settles down this is a small thing to swap.
