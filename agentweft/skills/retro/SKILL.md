---
name: retro
description: how to read a run's failed attempts and say what to change
role: retro
---

- take the failed attempts in the order they ran, one section each:

    ## seq <n> <step>
    failed: <what failed, in the runner's words>
    why: <the cause the record shows, or "not in the record">
    change: <the gate, prompt or flow.yaml key to change> - <the change>

- a change names a file and the line or key in it, never "improve the prompt"
- attempts that failed for one cause share one change, said once
- a cause outside the flow (the provider, the place, the task) says so and changes nothing
- end with `## change first` and the one change that would have saved the most attempts
- nothing else: no verdict, no handoff block
