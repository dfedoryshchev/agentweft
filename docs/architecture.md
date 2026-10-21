# architecture

four things, in the order a run goes through them.

## flow

`flow/spec.py`. a `FlowSpec` is flow.yaml parsed: name, steps, promises, and
whatever else the file carries. the promises block is the only part the runner
treats as meaning rather than config - the invariants get appended to every
role's rules.

## roles

`roles/resolver.py`. works out what each role is actually sent, once per run.
that is the shared fragments, plus the skills, plus the flow's own
instructions, plus the promises. some roles get extra: the reviewer and verify
get told they are allowed to say the work is wrong.

## runner

`runner/engine.py` is where a run starts. `begin.py` reads the command line and
sets the run up, fresh or carried on; `loop.py` runs the steps and holds every
way a run stops; `ending.py` writes the journal, the index and the saved
answer. what a step's answer has to get past is in `gating.py`, a step that
asks instead of going on is in `asking.py`, and `once.py` is the run the evals
make, which hands back the answer instead of printing it; the preflight and
the boundary note both use are in `gating.py`, so the two take the same steps.

`runner/run.py`. `Run` holds everything a step needs so nothing has to be
threaded through five functions. `Run.step()` is the only place a step becomes
a call. a step returns a `Handoff` - role, output, verdict, meta - not a string,
because the reviewer's verdict was being smuggled through the text.

fanout is the one branch in how a step is run: if a step is marked `fanout`,
the previous step's output is split into `TASK:` blocks (`runner/fan.py`) and
each one gets its own worker (`runner/fanout.py`), up to `workers` at a time. tasks that name the
same file under `FILES:` go one after another, and a task that wrote a file it
did not name, or a file two tasks wrote, stops the run.

`reports` is the one branch in what a step is handed. a step that names the
reports it judges gets those steps' output under their own names, assembled by
`orchestrate/synthesise.py`, instead of whatever ran immediately before it.

## providers

`providers/` is who answers. one method, `ask(prompt, timeout) -> Reply`, and a
`check()` that says whether the thing is usable without spending anything. cli,
api and fake register themselves the same way gates do.

the engine has not shelled out directly since may. that mattered less for the
http support than for the fake: the tests used to monkeypatch `subprocess.run`,
which meant every test knew how a call was made.

## guardrails

`guardrails/` is the layer that says no. `budget.py` counts calls and
tokens, as the provider reported them or estimated where it reported nothing,
and parks the run before the step that would take it over what the flow
declared.
`promises.py` checks the output against the flow's own invariants afterwards -
the prompts are told the same rules, but being told is not being checked.
`defaults.py` exists because a flow saying nothing about cost used to mean no
limit at all.

none of those is a prompt. that is the whole design: a control that can be
talked out of it is not a control.

`boundary.py` is the one thing in here that is half a prompt, and it is filed
under a different word for that reason. a step's `tools` grant goes out with
the role's rules and the answer is read back against it, because the model's
tool calls happen somewhere this runner is not. it is a check, it produces a
record, and it does not stop a run - `docs/guardrails.md` is exact about why
that is the design rather than the shortfall.

## gates

`guardrails/gates/` is the extension point. a gate has a name, options from
flow.yaml, and `run(text) -> Result`. they register themselves into a dict at
import; `build()` raises on an unknown name rather than skipping it, because a
typo in a gate name silently disabling a check is exactly the failure this
layer exists to prevent.

`command` is the one that matters: it runs anything with a cli and looks at the
exit code, so a check does not have to be code in here.

## mcp, both ends

`agentweft/mcp/` is the only part of this that talks to anything outside the
process, and it does it in both directions over the same `transport.py`.

`server.py` publishes what the flows did: the journal, the weekly rollup, gate
results, and every recent run, plus a `run_flow` tool behind a short allowlist.
`client.py` is the other direction - a flow asking something else what it
knows. `context.py` turns that into planner prompt text; `preflight.py` turns
it into a check with a threshold, which is the part that can stop a run.

the split matters: context is advice a model can ignore, preflight is a number
compared to a number. everything in here that is load bearing is the second
kind.

## state and journal

`runner/state.py` is one small json file per flow: what it last processed.
one file per flow, not one file with a key per flow - two runs at once used to
read the whole thing, edit their own key and write it all back, and whichever
finished last wiped the other one out.

`runs/journal.md` is a `running` line when a run starts and one more when it
ends: when, which flow, ok or stopped at which step, how long, the run id, and
then the output file or the stop's cause and why, with what the run spent.
`runner/stops.py` holds the shapes and the fixed list of causes, and reads the
lines back for `--resume`, `rollup.py` and `run.py spend`.

`runs/<run-id>/` holds each step's output as it is produced, and
`manifest.json`, written by `runner/manifest.py`: each step's state, what the
run has spent, a digest of the flow folder and of what each step produced,
the place's HEAD and changed files, the task and the run the task started as.
that is what makes resume possible: `--resume <run-id>` reads that run's
manifest, starts at the first step nothing passed for, and hands it whatever
the step before it produced. without the outputs on disk resume could tell
you where it died and nothing else.

`runs/<run-id>/steps.jsonl` is one json line per step run, written by
`runner/trace.py` whatever the step's fate: who answered, what it was counted
at and cost, the gate verdicts, what happened next and why. each pass's output
is kept as `steps/<seq>-<step>.md` beside it, so a redo does not lose the pass
before it. `docs/journal.md` has the fields.
