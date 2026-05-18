# examples

these run on the fake provider, so they work from a fresh clone with no key and
no folders of mine. swap `provider: fake` for `provider: cli` to run them for
real.

flows you can run without any of my folders existing.

    python run.py --flows examples minimal

- `minimal` - one role, one step. the smallest thing that is still a flow.
- `two-step` - a worker and a reviewer that can send the work back.
- `watch` - planner, worker, reviewer. the shape most of mine ended up in.
