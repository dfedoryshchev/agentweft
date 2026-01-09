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

## state and journal

`runner/state.py` is one small json file per flow: what it last processed.
`runs/journal.md` is one line per run. `runs/<run-id>/` holds each step's
output, which is what makes resume possible.
