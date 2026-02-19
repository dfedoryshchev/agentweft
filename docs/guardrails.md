# guardrails

three things stop a flow doing something stupid. none of them are prompts,
which is the point - a prompt asking nicely is not a control.

## the spend cap

    max_calls: 20
    max_tokens: 120000

checked after every step. over it and the run stops, writes `over budget at
<step>` to the journal, and keeps what it has. a flow that says nothing gets
the defaults in `guardrails/defaults.py` - no cap is the wrong default for the
thing that spends money.

token counts are characters over four. that is a guess and it is meant to be:
i want to know when a run is ten times bigger than usual, not what it cost to
the penny.

## the promises

    promises:
      invariants:
        - no file appears in two lists
        - needs me is at most 5 lines
        - every line names a file

these go into every role prompt AND get checked afterwards. the checking is
deliberately dumb - a handful of shapes i can actually assert. anything it
cannot check it reports as not checkable rather than passing quietly, because
a green tick you cannot trust is worse than no tick.

## the gates

    steps:
      - role: worker
        must_produce: "FAILS:"

a step can be required to have produced something before the next one runs.
fix-with-test uses it: the patcher does not run until the worker has actually
shown a failing test. red before green is the flow, not a preference.
