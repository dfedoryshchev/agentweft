# the journal, and picking a run back up

## what gets written

every run appends a `running` line to `runs/journal.md` before its first
step, and one more line when it ends:

    2026-01-22 09:14  weekly digest  running  0s  weekly-digest-2026-01-22-091402
    2026-01-22 09:14  weekly digest  ok  42s  weekly-digest-2026-01-22-091402  weekly-digest-2026-01-22-1.md  5 calls, 600 tokens counted (input 500, output 100) (cli x5)
    2026-01-22 18:02  ops-check  failed at reviewer.md  11s  ops-check-2026-01-22-180207  gate failed  3 calls, ~900 tokens estimated (cli x3)  regex: no line starts with "- ["
    2026-01-22 18:40  ops-check  parked at planner.md  9s  ops-check-2026-01-22-184011  parked  1 call, ~300 tokens estimated (cli x1)  waiting for user

the columns are split by two spaces: when the run started, the flow, how it
ended, how long it took, the run id. a finished run then has the file it
saved and what it spent; a stopped run has its cause, what it spent and why.
what it spent is counted, estimated or mixed (see "the spend cap" in
`guardrails.md`); `python run.py spend` prints the last twenty lines that say.

a run saves its output as `runs/<flow>-<day>-<n>.md`, and the first run of a
day is `-1`.

## why a run stopped

a run that stops short says `parked at <step>` when it is waiting for someone
and `failed at <step>` otherwise, and its cause is one of a fixed list:

- `gate failed` - a gate failed the step, or the step did not give the router
  what the flow requires of it (an output it must contain, a verdict it can
  read). the why is the gate and what it said.
- `refused` - the step was not allowed to start (the place changed under it)
  or its output was refused (a preflight in `refuse` mode).
- `parked` - the flow asked for a person, a preflight parked, the work ran out
  of redos, or files git cannot give back were changed.
- `provider outage` - the account's own limit refused the call: a session,
  weekly or usage limit. the run parks after that one call, never retries and
  never hands the empty answer to a gate; the why and `handoff.md` say when
  the provider said it resets, or `unknown`.
- `budget` - the call or token cap.
- `exception` - something raised; the traceback is printed as well.
- `interrupt` - Ctrl-C.
- `no answer` - the step came back empty after its retries. the why carries
  the last thing the provider said.

the same cause and why go on the step's line in `steps.jsonl` and into
`runs/<run-id>/why.md`. a cause off the list is refused where the line is
written, and `rollup.py` refuses one it finds.

`run.py` exits 0 when the run finished (or was not due), 1 when it could not
start, 2 when it stopped, and 130 on an interrupt.

and every step's output lands under `runs/<flow>-<date>-<time>/`, one file per
step, as it is produced. `runs/` is the one beside `run.py`, not one in the
directory the run was started from, so `--resume`, `rollup.py` and the mcp
server find the same records from anywhere.

flows that run several times an hour set `journal: false` - code-review does.
they still write their step outputs, they just stay out of the weekly number.
they cannot be resumed: a run that finished is never written down, so the
journal cannot tell it from the last one that stopped, and `--resume` says so
instead of picking a finished run back up.

## what each step did

the journal line is the run. `runs/<run-id>/steps.jsonl` is the steps: one
json line every time a step runs, a redo's second pass included, written
whatever happened next - the run went on, sent the work back, parked, stopped
or crashed. the keys are always all there, in this order:

    {"seq": 1, "time": "2026-01-22T09:14:03", "step": "worker.md",
     "from": null, "to": "reviewer.md",
     "provider": "cli", "command": "claude", "model": "a-model",
     "model_reported": "a-model-1",
     "tokens": {"counted": true, "input": 12, "output": 4,
                "cache_read": 2, "cache_creation": 0},
     "cost": 0.25, "session": "s-1", "seconds": 8.4, "cached": false,
     "retries": {}, "gates": [{"gate": "length", "ok": true,
                               "detail": "1 lines"}],
     "ungated": false,
     "outcome": "ok", "cause": null, "why": null,
     "file": "steps/001-worker.md",
     "task_file": "task.md", "tasks": null, "handoff": null}

(one line on disk; wrapped here.)

- `seq` counts the steps run, from 1. a resumed run carries on from the last
  number of the run it picked up, so the two files read as one sequence.
- `from` is the step whose output this one was handed, `to` the one the run
  went to next: null when nothing came before, and when the run ended or
  stopped here.
- `model` is the id the provider sends, null for one that sends none (the fake,
  or a cli command other than claude). `model_reported` is what the provider
  said answered.
- `tokens` and `cost` are what the provider reported, summed over every go a
  retry took. `{"counted": false}` and a null cost mean it reported nothing:
  not zero, unknown. a cached answer sent nothing, so it costs 0 and is not
  counted.
- `retries` is the goes that failed, by cause (`{"transient": 2}`); null on a
  crash, where nothing knows how many there were.
- `gates` is `[]` for a step that declares none, and also for one whose line
  was closed before its gates were checked (refused, fenced, over budget,
  crashed). `ungated` tells them apart: `true` when the gates were checked and
  the step had none, `false` when it had some and `gates` holds what they
  said, null when the check never ran. `gates.md` says the same: an ungated
  step gets its heading and a `no gates` line under it.
- `outcome` is one of `ok`, `redo`, `parked`, `refused`, `over budget`,
  `gate failed`, `failed`, `crashed`. `cause` is the run's stop cause from the
  list above, null when it went on. `why` is the reason the run had in hand
  when it stopped there, null when it went on.
- `file` is what this pass produced, `steps/<seq>-<step>.md`. a redo's second
  review is a second file, so the finding that sent the work back is still
  there. `<step>` beside it is still the last pass, the one `--resume` reads.
  a step that crashed or was refused before it ran has no file.
- `task_file` is `task.md` when the run was given a task with `--task` or
  `--task-file`, kept beside the line as `runs/<run-id>/task.md`; null when it
  was not. the text is not on the line, so a long task is written once.
- a fanned-out step is one line: the totals at the top and a `tasks` list with
  each task's own seconds, tokens, cost, session and retries, in plan order.
  the gates judged the joined output, so they are on the line, not the tasks.
- `handoff` is reserved and null for now.

the time, the seconds and the session are the only parts that differ between
two runs of the same flow on the same answers.

## the week

    python rollup.py

reads the journal for the last 7 days: runs, stops and average duration per
flow, stops per cause, and any run that wrote `running` and never wrote how it
ended (the process was killed). `--failed` keeps only the runs that stopped.

## when a run dies

    python run.py weekly-digest --resume

finds the most recent run of that flow that stopped short, whatever the cause,
works out which steps are left, and hands the first of them whatever the step
before it produced last time. that is why the step outputs are on disk -
without them resume could tell you where it died and nothing more. a
`running` line is skipped: it says a run began, not how it ended.

a provider outage is written as a park, but the step it parked on got no
answer, so carrying on runs that step again.

    python run.py weekly-digest --resume weekly-digest-2026-01-22-1

picks a specific run instead of the most recent.

## when a run stops on purpose

a step can say who the run waits for once it is done:

    steps:
      - role: planner
        prompt: planner.md
        pause: user
      - role: worker
        prompt: worker.md

the planner runs, its output is written, its gates are checked, and then the
run stops. the journal says `parked at planner.md` where a death says `failed
at planner.md`, and the run leaves a `handoff.md` next to its step outputs:

    # parked: park-demo-2026-08-27-173348

    waiting for    user
    flow           park demo
    stopped after  planner.md

    nothing failed. planner.md finished and its checks passed. the flow
    asks for user here, so the rest of it has not run.

    ran
      planner.md      0.0s

    left
      worker.md

    what planner.md produced is in runs/park-demo-2026-08-27-173348/planner.md
    read it before carrying on. that file is what the next step gets handed,
    so editing it is how you change what the rest of the run works from.

    to carry on
      python run.py park-demo --resume park-demo-2026-08-27-173348

`--resume` is the same switch either way, and it does the two different things
the two ways of stopping deserve: a run that died starts again AT the step that
died, because that step produced nothing, and a run that parked carries on AT
THE STEP AFTER the one it parked on, because that step finished and the only
thing missing was the person.

the file the handoff points at is the whole gate. the next step is handed
whatever is in it at the moment you carry on, so reading it and leaving it
alone is approval, and editing it is a correction the rest of the run works
from.

`pause` on the last step of a flow does nothing: the run finishes and no
handoff is written. there is nothing behind that step for a person to hold up.

## reading it from an agent

`python mcp_server.py` exposes the journal, the weekly rollup, the gate results
and every recent run as resources. see `docs/mcp.md`. that turned out to be the
half of mcp i use.

## why, not just what

the journal says a run failed at the reviewer. it cannot say why the reviewer
is there, or why the retry count is three. `agentweft/orchestrate/decisions.py`
keeps that: one entry per decision, the decision as a heading and the reason
under it.

    # decisions

    ## 2026-09-24 14:03  keep three retries

    the provider's limit resets each minute, and three spans it.

it is a file in the codebase being worked on, not under `runs/`, so it goes
through review and history like the code it explains. `record(root, decided,
why)` appends to `<root>/decisions.md` and refuses an entry with no why;
`read(root)` gives every entry back, oldest first. entries are never
rewritten - a decision that turned out wrong gets a later one saying so.

nothing in the runner writes to it yet.

## what it does not do

a resumed run writes its own journal line. so a run that failed and was picked
up shows twice.
