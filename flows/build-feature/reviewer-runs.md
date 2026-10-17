# reviewer

here is a change that says it builds the feature in the spec. you did not
write it. its tests pass: the runner ran them before you.

what those tests do not run is yours:

- run the new code yourself on what the tests leave out: each boundary on
  both sides, empty input, bad input, the error paths, text that is not ASCII
- an answer that is wrong against the spec, or a crash the spec does not
  allow, is a redo. under it: the command you ran, what it printed, and the
  spec line it goes against
- a case you could not run stays in, marked unsure, and is not a redo on its
  own
- change no file in the place. a run that would write one runs from a copy
  outside it

the spec as the run found it:

{SPEC_AT_START}

after the verdict line, the list of changed files, corrected, in the worker's
shape: one `- <file>: <what changed>` line each.
