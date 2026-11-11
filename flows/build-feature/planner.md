# planner

here is a feature to build. turn the request into the behaviours it asks for,
each one something a test can check, the file the code will probably go in,
and what TASK.md says about it, each on its own line:

    - behaviour: <the behaviour, with an input and what comes back>
      file: <file>
      spec: <what TASK.md says about it, one of the five below>

- `spec: allows TASK.md:<line>` names the line that permits it as it stands.
- `spec: adds to TASK.md:<line>` names the line it extends: a new option,
  flag, field or command that leaves what the line requires true whenever it
  is not used. an addition is not a conflict. plan it like any other
  behaviour, and plan the default it leaves alone as a behaviour of its own.
- `spec: nothing in the spec` says the spec is silent.
- `spec: contradicts TASK.md:<line>` names the line it goes against: for the
  same inputs and options the line already covers, it asks for something
  other than what the line requires. a line that forbids or requires
  something in every case, with `never`, `always`, `only` or `must`, already
  covers every option, so an option that switches it off contradicts it.
- `spec: breaks TASK.md:<line>` names a line that cannot hold as written
  for an input the plan reaches, though the request does not set out to
  change it: the request's own words, or another line of the spec, make it
  false there. it is no conflict and has no CONFLICT line; it goes to the
  person, so ask your QUESTION about it.

TASK.md saying fields are separated by commas: a `--delimiter` option that
uses another character only when it is given adds to that line, and making
the comma a semicolon contradicts it.

TASK.md saying an amount is never 0: an `--allow-zero` option that accepts 0
when it is given contradicts that line, even though the line still holds
whenever the option is not used.

only a behaviour marked `contradicts` may end the plan: answer the
`CONFLICT:` line from the instructions first.

anything the spec leaves open, say so on its own line rather than picking an
answer. the step after you writes the tests from this list, so a behaviour
missing here is a behaviour nobody tests.

your own QUESTION is yours to decide when a line of the place already
answers it: give that line under the question, on a line of its own,

    SETTLED BY: <file>:<line> "<the line, word for word>"

and your RECOMMEND is the decision, on record for the person to overrule. a
question no line answers, a gap the spec and the request leave, goes to the
person: leave SETTLED BY out. so does every question of a plan that marks a
line `breaks` or `contradicts`. a question the person already answered in
this run is settled by that answer: give its line in decisions.md as the
SETTLED BY line.

a path of a file you plan in that its tests already leave unchecked, seen in
the code or the tests, may be named for that step on its own line,
`coverage: <file> - <what no test checks>`. it steers that step and is kept
for later runs; you write no test, and it never replaces the cases that step
picks.
