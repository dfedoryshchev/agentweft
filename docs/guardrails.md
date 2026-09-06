# guardrails

three things stop a flow doing something stupid. none of them are prompts,
which is the point - a prompt asking nicely is not a control.

a fourth one does not stop anything and says so on the tin. it is last, and
the reason it is in here at all is at the bottom.

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

## the boundary check, which is not a sandbox

    steps:
      - role: architect
        tools: [read, grep]

the workflow layer's agents have granted each other a list of tools since they
arrived - the architect gets `[read, grep]` and then argues it in prose a few
lines below, "you are deliberately given no shell and no write access". a step
can say it now, and something reads it.

**what it is not** is the thing the word makes you expect. this runner is not
in the path of the model's tool calls: a provider is handed a prompt and hands
text back, so there is no call here to catch and nothing to refuse. that is a
statement about THIS layer, not about the whole repo - the mcp server does own
a tool it publishes, and it has an allowlist on it because it can.

so a grant is two halves, and both are honest about which they are:

- the grant is put into the step's prompt, next to the role's own rules. that
  is asking, and asking is the weakest thing in here.
- what comes back is read against it. that is `guardrails/boundary.py`, it is
  the same shape as the preflight - judge the output after the fact - and a
  finding goes to stdout and to `runs/<run-id>/boundary.md` beside the gate
  results.

it does not stop the run, and that is deliberate rather than unfinished. the
thing being reported has already happened somewhere this code was not; a stop
after the fact would look like prevention and buy a record. so it buys the
record and says so.

the marks are narrow the way the promise checks are. a shell block or a `$`
line is evidence of a shell; a diff is evidence of a file changing, and it
does not say whether the file existed first, so `write` answers for it as well
as `edit`. `read`, `grep` and `browser` leave no mark an output can carry, and
they are listed as unseeable rather than quietly passed - a grant that was
never checked must not read like one that came back clean.

a step that says nothing about tools has declared no boundary and none of this
runs for it. `tools: []` is a step saying it may touch nothing, which is a
boundary, and it is checked.
