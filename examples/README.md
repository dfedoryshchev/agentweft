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

## what they do not show

fanout, gates with an external command, preflight against a risk map. those
need either a real model or another tool running, so they live in `flows/`
where you can read them without running them.
