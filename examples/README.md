# examples

these run on the fake provider, so they work from a fresh clone with no key and
no folders of mine. swap `provider: fake` for `provider: cli` to run them for
real.

    python run.py minimal --force --flows examples

what they read is in here too: `_inbox/` and `_logs/`, a few files each. the
real flows take their folders from the env, which a fresh clone has none of, so
these name theirs instead. the underscore keeps them out of the flow list.

## what each one shows

- **minimal** - one role, one step. the smallest thing that is still a flow,
  and the one to copy if you are adding your own.
- **two-step** - a worker and a reviewer that can send the work back. make the
  worker sloppy and watch the redo happen, twice at most.
- **watch** - planner, worker, reviewer. the shape most of the real flows
  ended up in: something decides what the work is, something does it, something
  that did not do it says whether it is right.
- **personas** - the reviewer twice, from two fixed positions, and a judge
  that is handed both reports and has to decide. one role, two prompt files,
  and `reports: [worker, reviewer]` on the step that ends the argument.
- **tare-gate** - a reviewer told to source every number, and a command gate
  that checks it did. the check is [tare](https://github.com/dfedoryshchev/tare),
  a prose checker that exits 2 when a draft lands in the band named by
  `--fail-on` or a worse one, so the gate needs no adapter, only the exit code.
- **risk-map** - a worker checked against a risk map before it runs. a cold
  file goes through; a hot one parks the run, names the file and its score,
  and prints the `--resume` that carries on.

## tare-gate needs tare

it is the one example that runs something besides python. the gate calls
`dotnet run` on a tare clone next to this one, so it needs the .NET 10 SDK and

    git clone https://github.com/dfedoryshchev/tare.git ../tare
    python run.py tare-gate --force --flows examples

the path is relative to where the run works, which is where you started it
unless `--workdir` says otherwise. `dotnet run` builds tare before it runs it,
and a first build can take a while, which is why the gate gets 300 seconds.

the two answers are canned, in `_drafts/`. the worker's has four claims and
not one says where it came from; the reviewer's says where every number came
from and cuts the one the log cannot back. point the reviewer's `file:` at
`unsourced.md` and the run stops at the gate with tare's reason in
`runs/<run id>/gates.md`.

## risk-map

    python run.py risk-map --force --flows examples

start it from the top of the clone: the server's path is relative to where
the run works, and the plan's to where you started it.

the planner's answer is canned, `cold-plan.md`, and names
`src/util/format.ts`. before the worker runs, the files it was handed are
checked against the ranking the flow's `context:` block fetched, and that
one is cold, so the run goes through. point the planner's `file:` at
`hot-plan.md`, which names `src/store/session.ts`, and the run parks before
the worker:

    preflight: worker.md was handed 1 hot file(s)
      src/store/session.ts  1.0
    parked at worker.md, waiting for user

the handoff ends with the command that carries on, which runs the worker on
the plan as it stands: that is the go-ahead. this one keeps the journal, which
`--resume` reads to find where the run stopped.

the ranking comes from `server.py`, a stand-in for
[warpmap](https://github.com/dfedoryshchev/warpmap)'s mcp server: the same
json-rpc over stdio, the same `hotspots` tool needing `dir`, the same
`path  score` lines. it ranks the sample project from warpmap's readme
whatever `dir` says, so it needs no install and no network. to ask a real
warpmap instead, change the `context:` command and run it on your repo:

    command: ["warpmap", "mcp"]

    python run.py risk-map --force --flows examples --workdir <your repo>

warpmap ranks the files under `dir`, relative to the run's `workdir`, so a
plan only parks on a file your repo has and the map ranks hot.

## what they do not show

fanout, any other gate with an external command. those need either a real
model or another tool running, so they live in `flows/` where you can read
them without running them.
