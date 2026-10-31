---
name: retro
description: how to read a run's record, say what to change, and keep the project's facts and its runway of nice-to-do tickets
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
- then `## docs`, one line for each doc the record lists as naming what the run changed: `- <doc>: current` when every line it shows still holds for the code as left, or `- <doc>: ticket` with a `nice-to-do` fact below on that doc for the lines that no longer do; `- none listed` when the record lists none
- end with one FACTS block, even an empty one:

    FACTS
    fact:
      scope: <a file, a folder ending in /, a glob, or . for the project; one line each>
      kind: <decision, convention, why, defect, gate-issue or nice-to-do>
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
      kind: <gate or flow-key>
      where: <the key>
      what: <the program that would have caught it>
    END FACTS

- evidence is one of three, and the runner checks it: a line quoted from a file, a gate command and its exit code as `<command> exit <code>`, or `decisions.md <stamp>` of a ruling written in this run
- a fact is the WHY or the non-obvious way of one place, never a summary of what the code does; propose one only when this run showed it, at most the number the record allows
- a fact's `why:` rests on the evidence in the record, cited by `<file>:<line>`, a test or a ruling: what each step's reasons led to is listed where the runner found it in the record, and a fact that leans on one cites that place
- every stale fact gets a re-anchor with evidence, a supersede or a retire; one you cannot judge is left as it is
- a failed attempt, a gate issue or a refused write that a program could have caught gets a guard; a guard is a test, a gate or a key, never a sentence for a prompt. a gate or key guard is a `guard` item, for a person to make
- you change no file of the tree, and the runner makes no change for you. a test that would have caught it, and a doc, rules or instruction file (CLAUDE.md, AGENTS.md, .claude/, rules/) this run showed wrong, is a `nice-to-do` fact: one file in its one `scope`, the file the change is made in (the test file it goes in, or the code it tests when there is none yet, or the doc); a claim that says the change in one line, at most 200 characters, of one function, one passage or a few lines, naming no other file and never a refactor, rewrite, move or split; a `why` from this run; evidence as for any fact. the planner of a later run that touches that file is handed it and plans it in, and that run's gates hold it. a test for a defect the run left in place says so in its claim: it fails until the defect is fixed. a `check`, when given, finds what the tidy takes away, so it stops holding once the tidy is made. at most the number of tickets the record allows
- a defect a step found beside the change and did not fix is a `defect` fact on its file, its evidence the line it is at, with a `nice-to-do` for the test that would show it. one fixed by a test needs neither. a place a step names as maybe sharing the defect, one it did not read, you read: when the same gap is there, the `defect` fact's claim names it by file and line and its scope takes that file too; when it is not, retro.md says so in one line and no fact is written for it
- an open question two or more steps raised, that no ruling settled, is a `why` fact labelled `investigation` on the file whose code as left answers it: the claim says the question is open and what the code does now, the why says which steps raised it, its evidence the spec or code line it turns on, so a later run sees it open instead of settling it another way. the handoff's open questions and doubts name every role that raised each
- the why of a decision or a ruling, and how the code as left meets it, is a `why` or `decision` fact labelled `important`; a clause that says some part of it is still open does not make it an `investigation` fact
- the tests the red-first gate ran green without the change are the runner's to keep: it writes them as one `why` fact labelled `pins` on their test files, outside the number the record allows, and refuses a fact of yours on those files that names one of them and says it passes, is green or pins, or holds without the change: that is its note again. another point about one of them is yours to write
- a convention a pattern can show gets a check: one grep (flags -n -r -E -F -i -w, `--include=<glob>`) over files in its scope and the exit code that means it holds, 1 for a line that must never appear. the runner runs it itself, refuses a fact whose check does not hold now, and runs it again after every step that changes the scope. a convention whose claim says every, each, all, always, never, none, nowhere, only, single, sole, any or no (as a word: not python's `None`, a `--no-` flag or "no longer") is kept only with a check a line against it breaks, `exits 1`: with no check, or with an `exits 0` grep that one matching line holds, it is refused. a check refused for its form (a `|` in an `-E` pattern, a path outside the fact's scope) is still run: one that does not hold refuses the fact, and so does one that reads no file. a fact whose check cannot run, or runs and holds but is refused for its form, is kept without it, marked `unchecked:` with the reason; such a convention that says every or never is refused instead
- no secret, token or credential file name in any field, and never a `|` outside a check
- nothing else: no verdict, no handoff block
