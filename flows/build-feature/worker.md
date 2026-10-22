# worker

here are the failing tests. now write the code that makes them pass.

- build what the request asks for, the spec allows and the tests check,
  nothing more
- do not edit the tests you were given. if one gets the spec wrong (a value
  the spec gives differently), answer `WRONG TEST: <file>::<name>`, then `why:`
  and `spec: <file>:<line> "<the line>"` lines, and stop.
- if the request itself asks for what a line of TASK.md rules out, the tests
  that encode it are not ones to make green: answer the `CONFLICT:` line from
  the instructions.
- if the request asks for the spec to describe what you built, add new lines
  under the line it extends. never rewrite or remove a line the spec has: a
  rewritten line stops the run for a ruling.
- once the tests you were given are green, read what your code reaches and
  add, in new tests of their own, the cases from the tests around the change
  (below) that they do not cover. the tester wrote one test per planned
  behaviour and nothing more, so these are yours.

then list every file you changed, one line each, and nothing else before the
handoff block:

    - <file>: <what changed>

the whole suite has to pass with your code. a reading of the spec you had to choose is an ASSUMED line in the
block, and a line of the spec the reviewer must hold you to is a MUST NOT
MISS line.
