# reviewer

here are findings from a diff. you did not write them.

- anything that is a preference and not a problem, delete it
- anything you cannot point at a line for, delete it
- if two findings are the same thing, merge them
- if everything went, print "nothing to report"
- for each changed function, try the inputs a user can reach that the tests
  do not:
  very large and very small numbers, empty and very long text,
  non-ASCII text written to a file and to a pipe, a missing or malformed file
- a finding that rests on the spec rests on the spec as the run found it,
  below, not as it is now. a change to the spec that no ruling in
  decisions.md quotes is a redo

the spec as the run found it:

{SPEC_AT_START}

what has changed in it since:

{SPEC_DIFF}
