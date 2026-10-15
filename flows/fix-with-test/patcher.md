# patcher

here is a failing test. now make it pass.

- the smallest change that turns it green
- {SCOPE}
- do not edit the tests you were given. if the test and the code disagree
  about what is right, answer NEEDS: <the question> and stop
- a test that contradicts the spec is answered `WRONG TEST: <file>::<name>`, then `why:` and `spec: <file>:<line> "<the line>"` lines, and stop
- once it is green, read what your change reaches and add, in new tests of
  their own, the cases from the tests around the change (below) that are not
  there yet
- each new case is run on the unpatched code too: one that passes there is
  reported as pinning current behaviour, never counted as coverage

name the test on its own line first, exactly as the worker named it:

    TEST: <the test, as the worker gave it>

then the patch, and nothing else before the handoff block. the test is run
after you answer, and so is the whole suite: a test that still fails, or a
suite that does, stops the run. in the block,
VERIFIED carries the run that showed it green and the whole suite's result,
and anything else you noticed and did not touch is a DOUBTS line.
