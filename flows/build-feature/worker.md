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
- a case you find while building that no test covers gets a test of its own,
  written before the code for it. the cases to look for are the tests around
  the change, below.
- each new case is run on the code without yours too: one that passes there
  is reported as pinning current behaviour, never counted as coverage.

then list every file you changed, one line each, and nothing else before the
handoff block:

    - <file>: <what changed>

the whole suite is run after you answer, and a suite that does not pass stops
the run. a reading of the spec you had to choose is an ASSUMED line in the
block, and a line of the spec the reviewer must hold you to is a MUST NOT
MISS line.
