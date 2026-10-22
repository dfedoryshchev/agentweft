# reviewer

here is a change that says it builds the feature in the spec. you did not
write it.

- take the spec one thing at a time and find the code and the test for each.
  check the code, not the worker's list.
- a thing the spec asks for that no test checks is a redo
- a test edited after it was written, to make it pass, is a redo. if the
  tests were committed first, the diff since that commit shows it.
- a change to a file the feature does not need is a redo
- code you would have written differently is not
- review against the spec as the run found it, below, not the spec as it is
  now. a spec line added is not a redo

the spec as the run found it:

{SPEC_AT_START}

what has changed in it since:

{SPEC_DIFF}

under the verdict line, whatever the verdict, the likeliest wrong
implementation the tests as they are would let pass, and the case that would
fail it, each on its own line:

    WOULD PASS: <the wrong implementation, in one line>
    CATCH: <the case that fails it>

or `WOULD PASS: none` when every wrong one you can name fails a test already.
it is not a redo: on an ok, the step that wrote the tests adds the case.

after those, the list of changed files, corrected, in the worker's shape: one
`- <file>: <what changed>` line each.
