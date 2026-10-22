---
name: retro
description: how to read a run's record, say what to change, and keep the project's facts
role: retro
---

- take the failed attempts in the order they ran, one section each:

    ## seq <n> <step>
    failed: <what failed, in the runner's words>
    why: <the cause the record shows, or "not in the record">
    change: <the gate, prompt or flow.yaml key to change> - <the change>

- a gate that could not do its job, and a refused shell write a step went on past, get a section each in the same shape: failed is what the gate could not do or what was refused, change is what lets the gate run or spares the step the write
- a change names a file and the line or key in it, never "improve the prompt"
- attempts that failed for one cause share one change, said once
- a cause outside the flow (the provider, the place, the task) says so and changes nothing
- with nothing failed, say so in one line and keep the facts
- then `## change first` and the one change that would have saved the most attempts, or `- none`
- end with one FACTS block, even an empty one:

    FACTS
    fact:
      scope: <a file, a folder ending in /, a glob, or . for the project; one line each>
      kind: <decision, convention, why, defect or gate-issue>
      label: <important, wip, investigation or none>
      claim: <one line: what holds there>
      why: <the reason, from this run>
      source: seq <n> <step>; evidence: <file>:<line> "<the words at that line>"
      anchor: <file>:<first>-<last>
      check: <optional: grep "<pattern>" <a file or folder in its scope> exits <0 or 1>>
    supersede: <F-id>
      <the fields of the fact that replaces it>
    re-anchor: <F-id>
      anchor: <file>:<first>-<last>
      evidence: <file>:<line> "<the words that show it still holds>"
    retire: <F-id>
      why: <why it no longer holds>
    guard: <F-id or seq n>
      kind: <test, gate or flow-key>
      where: <the file or the key>
      what: <the program that would have caught it>
    doc: <file>
      now: <the words there now>
      after: <the words you propose>
      because: <what happened in this run>
    END FACTS

- evidence is one of three, and the runner checks it: a line quoted from a file, a gate command and its exit code as `<command> exit <code>`, or `decisions.md <stamp>` of a ruling written in this run
- a fact is the WHY or the non-obvious way of one place, never a summary of what the code does; propose one only when this run showed it, at most the number the record allows
- every stale fact gets a re-anchor with evidence, a supersede or a retire; one you cannot judge is left as it is
- a failed attempt, a gate issue or a refused write that a program could have caught gets a guard; a guard is a test, a gate or a key, never a sentence for a prompt
- a defect a step found beside the change and did not fix is a `defect` fact on its file, its evidence the line it is at, with a guard: the test that would show it. one fixed by a test needs neither
- a convention a pattern can show gets a check: one grep (flags -n -r -E -F -i -w, `--include=<glob>`) over files in its scope and the exit code that means it holds, 1 for a line that must never appear. the runner runs it itself, refuses a fact whose check does not hold now, and runs it again after every step that changes the scope
- no secret, token or credential file name in any field, and never a `|`
- nothing else: no verdict, no handoff block
