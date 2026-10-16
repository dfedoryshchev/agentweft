## the tests around the change

the tests you were given are the start, not the job. the job is every
behaviour the change can reach, asserted, and these cases are written once the
change is green, never before: the first tests are checked against the spec
first, and a case written ahead of that check is spent on a request that may
be stopped. take each interface the change
touches - a function, a command, a file it reads or writes - at each level
switched on below. read it from the code side: what it takes in, what it gives
back, and who calls it. list the behaviours it permits before writing a test,
then assert each one:

- behaviours: every distinct thing the code can do, each branch it can take
  and each result it can return
- inputs, by class: each valid class; both sides of every boundary (the last
  value that works and the first one that does not); empty, zero, very large,
  very long, non-ASCII, malformed and missing; every type and format the
  interface accepts
- outputs, by shape: every form the result can take; the error messages and
  exit codes; the files written, and nothing left half written when it fails;
  what goes to stdout and what goes to stderr
- every error path a user can reach
- each caller or command the changed code feeds: one case through that caller,
  not only through the function itself
- options together: each pair where one option changes what another does

each case covers a behaviour no other case covers. a case a test already
covers is not added, and two cases that differ only by a value the code treats
the same way are one case. one behaviour per test, named for what it checks;
several values for one behaviour are one parametrized test, not a loop inside
a test. there is no number of cases to reach. stop when every behaviour the
code permits is asserted, and not before: a behaviour left out is a gap in the
tests, and a gap is a defect.

take each expected value from the spec or the report, never from running the
code and copying what it gives back. when the spec does not decide a case, do
not decide it yourself. put it on a line of its own and go on with the rest:

    NEEDS: <the case, and what the spec leaves open>
    RECOMMEND: <the answer you would pick, and why>
    SIZE: <what that answer costs: one line, one file, a design change>

that line is for a real gap in the spec only, never for a question the code
can answer.

a case that still fails once the change is in is something the change
missed: fix the code, not the case.

the levels for this run:

{TEST_LEVELS}

a unit test calls one function directly. an integration test goes through the
project's entry point - its command or its main module - the way a user starts
it, in a temporary directory. an e2e test runs the whole product as it ships,
with the real services it talks to. at every level that is on, the list above
applies to the interface that level tests.
