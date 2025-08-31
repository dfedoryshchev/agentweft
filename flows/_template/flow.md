---
name: CHANGE ME
steps: planner, worker, reviewer
timeout: 300
retries: 3
---

one sentence saying what this is for.

## state

the runner remembers the last run per flow in state.json. if this flow should
only look at what is new, say so in the planner prompt and it gets handed the
last run name. if it should always look at everything, ignore it.
