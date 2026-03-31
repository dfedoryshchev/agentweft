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

`runner/engine.py`. `Run` holds everything a step needs so nothing has to be
threaded through five functions. `Run.step()` is the only place a step becomes
a call. a step returns a `Handoff` - role, output, verdict, meta - not a string,
because the reviewer's verdict was being smuggled through the text.

fanout is the one branch: if a step is marked `fanout`, the previous step's
output is split into lines and each one gets its own worker, up to `workers`
at a time.

## guardrails

`guardrails/` is the layer that says no. `budget.py` counts calls and rough
tokens and stops the run when a flow goes over what it declared.
`promises.py` checks the output against the flow's own invariants afterwards -
the prompts are told the same rules, but being told is not being checked.
`defaults.py` exists because a flow saying nothing about cost used to mean no
limit at all.

none of it is a prompt. that is the whole design: a control that can be talked
out of it is not a control.

## gates

`guardrails/gates/` is the extension point. a gate has a name, options from
flow.yaml, and `run(text) -> Result`. they register themselves into a dict at
import; `build()` raises on an unknown name rather than skipping it, because a
typo in a gate name silently disabling a check is exactly the failure this
layer exists to prevent.

`command` is the one that matters: it runs anything with a cli and looks at the
exit code, so a check does not have to be code in here.

## state and journal

`runner/state.py` is one small json file per flow: what it last processed.
one file per flow, not one file with a key per flow - two runs at once used to
read the whole thing, edit their own key and write it all back, and whichever
finished last wiped the other one out.

`runs/journal.md` is one line per run: when, which flow, ok or failed at which
step, how long, and the output file. `rollup.py` reads it for the week.

`runs/<run-id>/` holds each step's output as it is produced. that is what makes
resume possible: `--resume` finds the last failed run in the journal, works out
which steps are left, and hands the step before it whatever it produced last
time. without the outputs on disk resume could tell you where it died and
nothing else.
