# planner

here is a feature to build. turn the request into the behaviours it asks for,
each one something a test can check, the file the code will probably go in,
and what TASK.md says about it, each on its own line:

    - behaviour: <the behaviour, with an input and what comes back>
      file: <file>
      spec: <what TASK.md says about it, one of the four below>

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
