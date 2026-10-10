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

## what they do not show

fanout, preflight against a risk map, any other gate with an external command.
those need either a real model or another tool running, so they live in
`flows/` where you can read them without running them.
